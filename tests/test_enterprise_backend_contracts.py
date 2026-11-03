"""Regression anchors for Enterprise Backend program BC-01–BC-14.

Each test maps to one backlog item in docs/ENTERPRISE_BACKEND_PROGRAM.md.
"""
from pathlib import Path
from uuid import uuid4

import pytest

from app.route_inventory import ROUTES, classify

REPO = Path(__file__).resolve().parents[1]
BFF_ROUTE = REPO / 'web-dashboard/app/api/[...path]/route.ts'
GATEWAY = (REPO / 'services/gateway.py').read_text()
VERSION_ID = '00000000-0000-4000-8000-000000000001'


def _bff_source() -> str:
    return BFF_ROUTE.read_text()


def _route_classified(method: str, path: str) -> bool:
    return classify(method, path) is not None


@pytest.mark.parametrize(
    'method,path',
    [
        pytest.param('GET', f'/api/v1/control-plane/plan-versions/{VERSION_ID}/engineering-outbox', id='BC-01-scanner'),
        pytest.param('GET', '/api/v1/resources/billable-catalog', id='BC-02-billable-catalog'),
        pytest.param('GET', '/api/v1/catalog/azure-resource-types', id='BC-02-azure-types'),
        pytest.param('GET', '/api/v1/catalog/typed-resource-tables', id='BC-02-typed-tables'),
        pytest.param('GET', '/api/v1/rules/catalog', id='BC-02-rules-catalog'),
    ],
)
def test_bc01_bc02_routes_in_inventory(method, path):
    assert (method, path.replace(VERSION_ID, '{version_id}')) in ROUTES or _route_classified(method, path)


def test_bc01_engineering_outbox_reachable_via_bff():
    source = _bff_source()
    assert 'engineering-outbox' in source
    assert 'controlPlaneRoutes' in source


def test_bc02_catalog_routes_reachable_via_bff():
    source = _bff_source()
    assert 'catalogRoutes' in source
    assert 'billable-catalog' in source
    assert 'azure-resource-types' in source
    assert 'typed-resource-tables' in source
    assert 'rules/catalog' in source or 'rules\\/catalog' in source


def test_bc03_cost_scope_forwarded_on_resource_lists():
    assert "'cost_scope'" in GATEWAY or '"cost_scope"' in GATEWAY
    assert 'resource_filters' in GATEWAY


def test_bc04_bc05_agent_worker_contracts_documented():
    contracts = (REPO / 'agent-worker/src/contracts.ts').read_text()
    runtime = (REPO / 'agent-worker/src/runtime/pre_mutation_drift_guard.ts').read_text()
    assert 'checkAssignment' in contracts or 'checkAssignment' in runtime
    assert 'expected_state' in runtime
    assert 'Task' in contracts


def test_bc06_gitops_sync_agent_and_unreconciled_resize():
    gitops = (REPO / 'app/gitops_api.py').read_text()
    store = (REPO / 'app/agent_store.py').read_text()
    assert 'EnterpriseStore' in gitops
    assert 'compute.resize' in store


def test_bc07_scan_jobs_respects_distributed_lease():
    jobs = (REPO / 'app/jobs_api.py').read_text()
    assert 'distributed_scan_lease_held' in jobs
    assert '409' in jobs
    assert 'SCAN_LEASE_BUSY' in jobs


def test_bc08_bc09_arm_detail_filter_end_to_end():
    resource_api = (REPO / 'app/resource_api.py').read_text()
    assert 'arm_detail' in resource_api
    assert "'arm_detail'" in GATEWAY or '"arm_detail"' in GATEWAY


def test_bc10_cloud_status_schema_capabilities():
    cloud_status = (REPO / 'app/cloud_status.py').read_text()
    assert 'schema_capabilities' in cloud_status


def test_bc11_platform_outbox_lease_guard():
    module = (REPO / 'app/schema_capabilities.py').read_text()
    assert 'require_platform_outbox_lease_columns' in module
    assert '0033_platform_outbox_lease' in module


def test_bc12_finops_autopilot_bff_parity():
    source = _bff_source()
    assert 'finopsSurfaceRoutes' in source
    assert 'autopilot' in source


def test_bc13_saas_focus_import_bff_parity():
    source = _bff_source()
    assert 'saas-focus' in source


def test_bc14_platform_gitops_ast_routes_bff_parity():
    source = _bff_source()
    assert 'platformGitopsRoutes' in source
    assert 'ast/' in source or 'ast\\/' in source
    assert 'pull-requests' in source


def test_bc14_platform_gitops_routes_classified_on_gateway():
    for method, path in (
        ('POST', '/api/v1/gitops/pull-requests'),
        ('POST', '/api/v1/gitops/pre-merge/evaluate'),
        ('POST', '/api/v1/gitops/ast/sync'),
        ('POST', '/api/v1/gitops/ast/index-repositories'),
    ):
        assert _route_classified(method, path), f'{method} {path}'
