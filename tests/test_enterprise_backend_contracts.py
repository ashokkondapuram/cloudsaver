"""Behavioral regression anchors for Enterprise Backend program BC-01–BC-14."""
import hashlib
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.route_inventory import ROUTES, classify
from services.gateway import create_app as gateway_app

REPO = Path(__file__).resolve().parents[1]
BFF_ROUTE = REPO / 'web-dashboard/app/api/[...path]/route.ts'
TID = '11111111-1111-4111-8111-111111111111'
SID = '33333333-3333-4333-8333-333333333333'
KEY = 'test-enterprise-backend-key-32-chars!!'
VERSION_ID = '00000000-0000-4000-8000-000000000001'
SCAN_ID = '44444444-4444-4444-8444-444444444444'


class Limiter:
    async def check(self, tenant_id):
        return None


def _settings(tmp_path):
    from app.config import Settings
    return Settings('azure', str(tmp_path / 'bc.sqlite3'), (
        dict(tenant_id=TID, name='BC', subscription_ids=[SID], roles=['TenantAdmin'],
             api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest()),
    ))


def _bff_source() -> str:
    return BFF_ROUTE.read_text()


def _bff_regex(name: str) -> re.Pattern[str]:
    source = _bff_source()
    match = re.search(rf"const {name}=/\^(.+)\$/;", source)
    assert match, f'Missing BFF route group {name}'
    return re.compile('^' + match.group(1) + '$')


@pytest.mark.parametrize(
    'method,path,kind',
    [
        ('GET', f'/api/v1/control-plane/plan-versions/{VERSION_ID}/engineering-outbox', 'scoped_read'),
        ('GET', '/api/v1/resources/billable-catalog', 'scoped_read'),
        ('GET', '/api/v1/catalog/azure-resource-types', 'scoped_read'),
        ('GET', '/api/v1/catalog/typed-resource-tables', 'scoped_read'),
        ('GET', '/api/v1/rules/catalog', 'scoped_read'),
        ('POST', '/api/v1/gitops/pull-requests', 'scan_write'),
        ('POST', '/api/v1/gitops/ast/sync', 'full_scope'),
    ],
)
def test_bc_routes_classified_in_inventory(method, path, kind):
    templated = path.replace(VERSION_ID, '{version_id}')
    assert (method, templated) in ROUTES or classify(method, path) == kind


@pytest.mark.parametrize(
    'group,sample',
    [
        ('controlPlaneRoutes', f'v1/control-plane/plan-versions/{VERSION_ID}/engineering-outbox'),
        ('catalogRoutes', 'v1/resources/billable-catalog'),
        ('catalogRoutes', 'v1/catalog/azure-resource-types'),
        ('finopsSurfaceRoutes', 'v1/finops/autopilot/playbooks'),
        ('finopsSurfaceRoutes', 'v1/finops/saas-focus/import'),
        ('platformGitopsRoutes', 'v1/gitops/pull-requests'),
        ('platformGitopsRoutes', 'v1/gitops/ast/sync'),
    ],
)
def test_bc_bff_allowlist_matches_sample_paths(group, sample):
    assert _bff_regex(group).match(sample)


def test_bc03_bc08_gateway_forwards_resource_query_params(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen['path'] = request.url.path
        seen['query'] = str(request.url.query)
        return httpx.Response(200, json={'scan_id': SCAN_ID, 'observed_at': '2026-01-01T00:00:00Z', 'total': 0, 'items': [],
                                         'summary': {'total': 0, 'ai_status': {}, 'ai_risk': {}, 'decision': {}, 'review_priority': {}}})

    client = TestClient(gateway_app(_settings(tmp_path), Limiter(), httpx.MockTransport(handler)))
    headers = {'Authorization': 'Bearer ' + KEY}
    response = client.get(
        f'/api/v1/scans/{SCAN_ID}/resources?cost_scope=all&arm_detail=collected&limit=10&offset=0',
        headers=headers,
    )
    assert response.status_code == 200
    assert seen['path'].endswith(f'/api/v1/scans/{SCAN_ID}/resources')
    assert 'cost_scope=all' in seen['query']
    assert 'arm_detail=collected' in seen['query']


def test_bc04_worker_exposes_check_assignment():
    contracts = (REPO / 'agent-worker/src/contracts.ts').read_text()
    assert re.search(r'\bcheckAssignment\b', contracts)


def test_bc05_worker_requires_expected_state_before_writes():
    runtime = (REPO / 'agent-worker/src/runtime/pre_mutation_drift_guard.ts').read_text()
    assert 'EXPECTED_STATE_REQUIRED' in runtime
    assert 'assertExpectedStatePresent' in runtime


def test_bc06_unreconciled_includes_compute_resize():
    store = (REPO / 'app/agent_store.py').read_text()
    assert 'compute.resize' in store


def test_bc07_scan_jobs_returns_409_when_lease_held(tmp_path, monkeypatch):
    monkeypatch.setattr('app.scan_concurrency.distributed_scan_lease_held', lambda _tenant: True)
    monkeypatch.setenv('CLOUDSAVER_INTERACTIVE_JOBS', 'true')
    monkeypatch.setenv('CLOUDSAVER_DELIVERY_ENABLED', 'true')

    class Repo:
        def submit(self, *args, **kwargs):
            raise AssertionError('submit should not run when lease is held')

    from fastapi import FastAPI
    from app.jobs_api import create_router as jobs_router

    settings = _settings(tmp_path)
    tenant = settings.tenants[0]
    app = FastAPI()
    app.include_router(jobs_router(settings, lambda: tenant, repository=Repo()))
    client = TestClient(app)
    response = client.post(
        '/api/v1/scan-jobs',
        headers={'Authorization': 'Bearer ' + KEY},
        json={'idempotency_key': '11111111-1111-4111-8111-111111111111', 'providers': ['azure']},
    )
    assert response.status_code == 409


def test_bc10_cloud_status_includes_schema_capabilities(tmp_path):
    from app.cloud_status import cloud_status
    tenant = dict(tenant_id=TID, subscription_ids=[SID])
    payload = cloud_status(tenant, {}, schema_capabilities={'typed_resource_tables': True})
    assert payload['schema_capabilities']['typed_resource_tables'] is True


def test_bc11_platform_outbox_lease_guard_raises():
    from app.schema_capabilities import require_platform_outbox_lease_columns

    class Row:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Db:
        def __init__(self, rows):
            self.rows = iter(rows)

        def execute(self, sql, params=None):
            return Row(next(self.rows, None))

    with pytest.raises(ValueError, match='0033_platform_outbox_lease'):
        require_platform_outbox_lease_columns(Db([(1,), None]))
