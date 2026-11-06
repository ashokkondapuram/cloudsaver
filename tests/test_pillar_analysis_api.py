"""Scan and resource API exposure for persisted pillar_analysis."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.analysis_service.pipeline import attach_pillar_analysis
from app.config import Settings
from app.domain.resource.identity import resource_key
from app.main import create_app
from app.store import Store
from tests.support import azure_disk_finding
from tests.test_enterprise import workspace as enterprise_workspace

TID = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
KEY = 'test-pillar-analysis-key-32-characters!!'


def auth():
    return {'Authorization': 'Bearer ' + KEY}


def tenant():
    row = enterprise_workspace()
    row['tenant_id'] = TID
    row['subscription_ids'] = [SUB]
    row['api_key_sha256'] = hashlib.sha256(KEY.encode()).hexdigest()
    return row


def completed_scan(*, with_pillar: bool = True):
    finding = azure_disk_finding(SUB)
    inventory_row = dict(
        finding,
        evidence=dict(finding.get('evidence') or {}, encrypted=False, disk_state='Unattached'),
    )
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        status='completed',
        mode='azure',
        cloud_providers=['azure'],
        subscriptions_scanned=1,
        total_items_found=1,
        total_monthly_waste_usd=None,
        realizable_monthly_savings_usd=None,
        findings=[finding],
        inventory=[inventory_row],
    )
    if with_pillar:
        attach_pillar_analysis(scan)
    return scan


@pytest.fixture
def client(tmp_path):
    settings = Settings('azure', str(tmp_path / 'pillar.db'), (tenant(),))
    store = Store(settings.database)
    scan = completed_scan()
    store.save(TID, scan, workspace=tenant())
    with TestClient(create_app(settings)) as test_client:
        yield test_client, scan


def test_scan_get_and_list_include_pillar_analysis(client):
    test_client, scan = client
    detail = test_client.get(f"/api/v1/scans/{scan['scan_id']}", headers=auth()).json()
    assert detail['pillar_analysis']['engine'] == 'analysis-service'
    assert len(detail['pillar_analysis']['account_pillar_scores']) == 5

    listed = test_client.get('/api/v1/scans', headers=auth()).json()
    assert listed[0]['scan_id'] == scan['scan_id']
    assert listed[0]['pillar_analysis']['finding_count'] == detail['pillar_analysis']['finding_count']


def test_pillar_analysis_endpoint_returns_block(client):
    test_client, scan = client
    block = test_client.get(f"/api/v1/scans/{scan['scan_id']}/pillar-analysis", headers=auth()).json()
    assert block == scan['pillar_analysis']
    assert test_client.get(f"/api/v1/scans/{uuid4()}/pillar-analysis", headers=auth()).status_code == 404


def test_pillar_analysis_endpoint_missing_when_not_computed(tmp_path):
    settings = Settings('azure', str(tmp_path / 'no-pillar.db'), (tenant(),))
    store = Store(settings.database)
    scan = completed_scan(with_pillar=False)
    store.save(TID, scan, workspace=tenant())
    with TestClient(create_app(settings)) as test_client:
        body = test_client.get(f"/api/v1/scans/{scan['scan_id']}", headers=auth()).json()
        assert body.get('pillar_analysis') is None
        assert test_client.get(f"/api/v1/scans/{scan['scan_id']}/pillar-analysis", headers=auth()).status_code == 404


def test_resource_detail_includes_pillar_scores_overlay(client):
    test_client, scan = client
    finding = scan['findings'][0]
    rk = resource_key('azure', finding['resource_id'])
    detail = test_client.get(f"/api/v1/scans/{scan['scan_id']}/resources/{rk}", headers=auth()).json()
    assert detail['pillar_scores'] == scan['pillar_analysis']['resources'][0]['pillar_scores']
    assert len(detail['pillar_scores']) == 5
