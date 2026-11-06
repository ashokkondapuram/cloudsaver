"""End-to-end scan pipeline with mocked Azure Resource Graph and billing (no real cloud)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.collectors import azure_resource_graph as arg
from app.collectors.billing_sync import COST_SOURCE_ACTUAL_BILLED
from app.config import Settings
from app.domain.resource.identity import canonical_resource_id, resource_key
from app.focus import FocusRepository
from app.resource_assessment import assessments, resource_key as assessment_resource_key
from app.scan_billing import materialize_scan_billing
from tests.test_enterprise import workspace
from tests.test_scanner import rest_page, row
from tests.test_worker import Lease, Repository, SUB, TENANT
from workers import tasks

pytest_plugins = ['tests.test_enterprise']


class Credential:
    """Minimal stand-in for app.cloud_identity.azure_credential (context manager + token)."""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        pass


def _inventory_disk():
    base = row('archive-export-disk', sub=SUB)
    base.update(
        id=f'/subscriptions/{SUB}/resourceGroups/review/providers/Microsoft.Compute/disks/Archive-Disk',
        name='archive-export-disk',
        location='eastus',
        diskState='Unattached',
        sizeGB=128,
    )
    return base


@pytest.fixture
def scan_pipeline_mocks(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'local')
    monkeypatch.setenv('CLOUDSAVER_SCAN_BILLING_REFRESH', 'true')
    monkeypatch.setenv(
        'CLOUDSAVER_BILLING_CONNECTORS',
        '[{"tenant_id":"'
        + TENANT
        + '","provider":"azure","scope_id":"'
        + SUB
        + '"}]',
    )
    monkeypatch.setattr('app.cloud_identity.azure_credential', lambda _tenant: Credential())
    monkeypatch.setattr('app.collectors.live_common.enabled', lambda *_args, **_kwargs: False)
    monkeypatch.setattr('app.collectors.azure_arm_detail.enabled', lambda *_args, **_kwargs: False)

    disk = _inventory_disk()

    def mock_post_page(_credential, body):
        query = body.get('query') or ''
        if 'isnotempty(id)' in query:
            return rest_page([disk])
        if 'diskState' in query and 'Unattached' in query:
            return rest_page([disk])
        return rest_page([])

    monkeypatch.setattr(arg, '_post_page', mock_post_page)

    billing_rows = []

    def fake_azure_rows(binding, tenant, start, end):
        observation = dict(
            day=start,
            resource_id=disk['id'].lower(),
            currency='USD',
            billed='11.00',
            effective='9.50',
            billed_present=True,
            effective_present=True,
            category='Usage',
            cost_source=COST_SOURCE_ACTUAL_BILLED,
        )
        billing_rows.append(observation)
        return [observation], 'resource', []

    monkeypatch.setattr('app.collectors.billing_sync.azure_rows', fake_azure_rows)
    return disk, billing_rows


def test_scan_pipeline_e2e_inventory_billing_and_resource_key(
    scan_pipeline_mocks, evidence, monkeypatch
):
    disk, billing_rows = scan_pipeline_mocks
    settings, enterprise_store, _saved = evidence
    tenant = workspace()
    tenant['tenant_id'] = TENANT
    tenant['subscription_ids'] = [SUB]
    settings = Settings('azure', settings.database, (tenant,), settings.database_url)
    monkeypatch.setattr('app.config.Settings.load', lambda: settings)
    repository = Repository()
    job_id = str(uuid4())

    result = tasks.run_scan_job(
        settings,
        TENANT,
        [SUB],
        job_id,
        repository,
        Lease(),
        scanner=None,
    )

    assert result['status'] == 'completed'
    scan = repository.scans[result['scan_id']]
    assert scan['status'] == 'completed'
    assert len(scan['inventory']) == 1
    inv = scan['inventory'][0]
    assert inv['resource_name'] == 'archive-export-disk'
    assert inv['cloud_provider'] == 'azure'
    assert inv['evidence'].get('size_gb') == 128

    canonical = canonical_resource_id('azure', disk['id'])
    expected_key = resource_key('azure', disk['id'])
    assert expected_key == resource_key('azure', canonical)
    assert inv['resource_id'] == disk['id']

    now = datetime.now(timezone.utc)
    assessment_rows = assessments(scan, now=now)
    assert expected_key in assessment_rows
    assessment = assessment_rows[expected_key][0]
    assert assessment['resource_key'] == expected_key
    assert assessment_resource_key(
        dict(cloud_provider='azure', resource_id=disk['id'])
    ) == expected_key

    focus = FocusRepository(enterprise_store)
    billed_scan = materialize_scan_billing(tenant, scan, focus)
    assert billed_scan['billing_materialized'] is True
    assert billing_rows and billing_rows[0]['cost_source'] == COST_SOURCE_ACTUAL_BILLED
    evidence_after = billed_scan['inventory'][0]['evidence']
    assert evidence_after.get('billed_cost_usd') == pytest.approx(11.0)
    assert evidence_after.get('effective_cost_usd') == pytest.approx(9.5)

    reassessed = assessments(billed_scan, now=now)[expected_key][0]
    assert reassessed['resource_key'] == expected_key
    assert reassessed['billed_cost_usd'] == pytest.approx(11.0)
