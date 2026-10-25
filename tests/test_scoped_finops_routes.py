"""Provider-scoped workspace keys can read FinOps, AI, and GitOps history they own."""
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.data_scope import metadata_visible, restricted, scan_visible
from app.focus import FocusRepository, ImportRequest
from app.inference_ledger import InferenceLedger
from app.provider_access import enforce_route
from tests.test_enterprise import batch, charge, evidence, workspace

AWS_ACCOUNT = '123456789012'


def aws_workspace():
    return dict(
        workspace(),
        aws_accounts=[{'account_id': AWS_ACCOUNT, 'region': 'us-east-1', 'role_arn': f'arn:aws:iam::{AWS_ACCOUNT}:role/Reader'}],
    )


@pytest.fixture
def limited_aws_tenant():
    return dict(aws_workspace(), allowed_providers=['aws'])


def test_enforce_route_allows_scoped_finops_and_ai_reads(limited_aws_tenant):
    for method, path in (
        ('GET', '/api/v1/finops/summary'),
        ('GET', '/api/v1/finops/imports'),
        ('GET', '/api/v1/ai/assessments'),
        ('GET', '/api/v1/ai/usage'),
        ('GET', '/api/v1/gitops/requests'),
    ):
        enforce_route(method, path, limited_aws_tenant, ['azure', 'aws'])


def test_enforce_route_still_blocks_true_full_scope_routes(limited_aws_tenant):
    with pytest.raises(HTTPException) as error:
        enforce_route('GET', '/api/v1/governance/access', limited_aws_tenant, ['azure', 'aws'])
    assert error.value.status_code == 403


def test_focus_summary_and_imports_exclude_other_providers(evidence, limited_aws_tenant):
    _, store, _ = evidence
    repo = FocusRepository(store)
    tenant = aws_workspace()
    azure_sub = tenant['subscription_ids'][0]
    repo.import_records(tenant, ImportRequest.model_validate(batch([
        charge(1, '40', ProviderName='AWS', BillingAccountId=AWS_ACCOUNT, SubAccountId=AWS_ACCOUNT),
    ], source_id='export-aws-2026-10', provider='aws', sub_account_id=AWS_ACCOUNT)))
    repo.import_records(tenant, ImportRequest.model_validate(batch([
        charge(2, '70'),
    ], source_id='export-azure-2026-10', provider='azure', sub_account_id=azure_sub)))
    summary = repo.summary(limited_aws_tenant, date(2026, 10, 1), date(2026, 10, 22), 'USD')
    assert summary['providers'] == [{'provider': 'aws', 'records': 1, 'billed_cost': '40.00000000', 'effective_cost': '40.00000000'}]
    imports = repo.imports(limited_aws_tenant, 10)
    assert len(imports) == 1 and imports[0]['provider'] == 'aws'


def test_inference_history_filters_unlabelled_and_foreign_provider_rows(evidence, limited_aws_tenant):
    _, store, scan = evidence
    ledger = InferenceLedger(store)
    tenant = aws_workspace()
    scan_id = scan['scan_id']
    allowed = ledger.run(
        tenant['tenant_id'], str(uuid4()), 'a' * 64, 10, lambda: dict(advice={'summary': 'ok'}, usage={'input_tokens': 1, 'output_tokens': 1}),
        metadata={'scan_id': scan_id, 'provider': 'aws', 'model': 'm', 'target_id': 't', 'source_provider': 'aws', 'scope_id': AWS_ACCOUNT},
    )
    ledger.run(
        tenant['tenant_id'], str(uuid4()), 'b' * 64, 10, lambda: dict(advice={'summary': 'hidden'}, usage={'input_tokens': 1, 'output_tokens': 1}),
        metadata={'scan_id': scan_id, 'provider': 'azure', 'model': 'm', 'target_id': 't', 'source_provider': 'azure', 'scope_id': tenant['subscription_ids'][0]},
    )
    page = ledger.page(limited_aws_tenant)
    assert [item['id'] for item in page['items']] == [allowed['assessment_id']]
    assert ledger.get(limited_aws_tenant, allowed['assessment_id']) is not None
    assert metadata_visible(limited_aws_tenant, {'provider': 'azure'}) is False


def test_scan_visible_respects_active_provider_filter(limited_aws_tenant):
    aws_scan = {'scan_id': 'aws-scan', 'cloud_providers': ['aws'], 'findings': [], 'inventory': []}
    azure_scan = {'scan_id': 'azure-scan', 'cloud_providers': ['azure'], 'findings': [], 'inventory': []}

    class ScanLookup:
        def get(self, tenant_id, scan_id):
            return aws_scan if scan_id == 'aws-scan' else azure_scan if scan_id == 'azure-scan' else None

    lookup = ScanLookup()
    assert scan_visible(lookup, limited_aws_tenant, 'aws-scan') is True
    assert scan_visible(lookup, limited_aws_tenant, 'azure-scan') is False
