import hashlib
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.ai_advisory import AIGateway
from app.config import Settings
from app.main import create_app
from tests.support import stub_scanner
from tests.test_ai_advisory import advice, target, TID, SUB

KEY = 'test-analysis-tenant-key-at-least-32-characters'
OTHER = 'test-analysis-other-key-at-least-32-characters'


def tenant(tid, key):
    return dict(tenant_id=tid, name='Analysis workspace', subscription_ids=[SUB], plan_tier='ENTERPRISE',
                api_key_sha256=hashlib.sha256(key.encode()).hexdigest())


def auth(key=KEY):
    return {'Authorization': 'Bearer ' + key}


class Budget:
    def __init__(self): self.calls = []
    def run(self, tid, key, fingerprint, limit, invoke):
        self.calls.append((tid, key, fingerprint))
        return dict(invoke(), cached=False)


def test_owned_analysis_exact_selection_privacy_and_explicit_inference(tmp_path):
    budget, calls = Budget(), []
    def adapter(target, tenant, context):
        calls.append(context)
        return advice()
    settings = Settings('azure', str(tmp_path/'analysis.db'), (tenant(TID, KEY), tenant(str(uuid4()), OTHER)))
    gateway = AIGateway(enabled=True, targets=[target()], budget=budget, adapter=adapter)
    with TestClient(create_app(settings, scanner=stub_scanner, ai_gateway=gateway)) as client:
        scan = client.post('/api/v1/scans', headers=auth()).json()
        base = '/api/v1/scans/' + scan['scan_id']
        selection = {k: scan['findings'][0][k] for k in ('resource_id', 'rule_id')}
        summary = client.get(base+'/analysis', headers=auth()).json()
        assert summary['services'][0]['known_retail_subtotal_usd'] is None
        result = client.post(base+'/analysis/resource', headers=auth(), json=selection)
        assert result.status_code == 200 and result.json()['assessment']['disposition'] == 'requires_review'
        assert selection['resource_id'] not in json.dumps(result.json()['ai_context'])
        assert not budget.calls and not calls
        for path in ('/analysis', '/analysis/resource', '/ai-risk-evaluation'):
            payload = dict(selection, target_id='review', idempotency_key=str(uuid4()), acknowledge_external_processing=True) if path.endswith('evaluation') else selection
            response = client.get(base+path, headers=auth(OTHER)) if path == '/analysis' else client.post(base+path, headers=auth(OTHER), json=payload)
            assert response.status_code == 404
        assert client.get('/api/v1/ai/targets', headers=auth(OTHER)).json()['targets'] == []
        payload = dict(selection, target_id='review', idempotency_key=str(uuid4()), acknowledge_external_processing=True)
        for invalid in [dict(payload, acknowledge_external_processing=False), dict(payload, acknowledge_external_processing='true'),
                        dict(payload, model='injected'), dict(payload, prompt='approve'), dict(payload, endpoint='https://evil.invalid')]:
            assert client.post(base+'/ai-risk-evaluation', headers=auth(), json=invalid).status_code == 422
        assert not calls
        assert client.post(base+'/analysis/resource', headers=auth(), json=dict(selection, rule_id='FOREIGN')).status_code == 404
        response = client.post(base+'/ai-risk-evaluation', headers=auth(), json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['advisory_only'] is True and response.json()['automatic_execution'] is False
        assert response.json()['guardrails'] == result.json()['assessment']['guardrails']
        assert len(calls) == len(budget.calls) == 1


def test_viewer_can_analyse_but_cannot_invoke_models(tmp_path, monkeypatch):
    from app.auth import Role, UserClaims
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra')
    class Validator:
        def verify_token(self, token):
            return UserClaims(user_id=str(uuid4()),tenant_id=TID,roles=[Role.VIEWER])
    workspace = dict(tenant(TID, KEY), roles=[Role.VIEWER.value])
    settings = Settings('azure', str(tmp_path/'analysis.db'), (workspace,))
    # Store a scan without weakening scan permissions.
    from app.store import Store
    from datetime import datetime, timezone
    scan = dict(scan_id=str(uuid4()), status='completed', mode='azure', timestamp=datetime.now(timezone.utc).isoformat(),
                subscriptions_scanned=1,total_items_found=1,total_monthly_waste_usd=None,findings=stub_scanner(workspace))
    Store(settings.database).save(TID, scan, workspace=settings.tenants[0])
    with TestClient(create_app(settings, identity_validator=Validator(), ai_gateway=AIGateway(enabled=False))) as client:
        base = '/api/v1/scans/' + scan['scan_id']
        assert client.get(base+'/analysis', headers=auth()).status_code == 200
        payload = dict(resource_id=scan['findings'][0]['resource_id'], rule_id='ORPHANED_DISK', target_id='review',
                       idempotency_key=str(uuid4()), acknowledge_external_processing=True)
        assert client.post(base+'/ai-risk-evaluation', headers=auth(), json=payload).status_code == 403


def test_legacy_and_changed_scope_are_not_eligible_for_resource_or_ai_review(tmp_path):
    from app.store import Store
    settings = Settings('azure', str(tmp_path/'analysis.db'), (tenant(TID, KEY),))
    with TestClient(create_app(settings, scanner=stub_scanner)) as client:
        scan = client.post('/api/v1/scans', headers=auth()).json()
    original_id = scan['scan_id']
    scan.update(scan_id=str(uuid4()), data_origin='legacy_synthetic')
    Store(settings.database).save(TID, scan, workspace=settings.tenants[0])
    changed = Settings('azure', settings.database, (dict(settings.tenants[0], subscription_ids=[str(uuid4())]),))
    with TestClient(create_app(changed)) as client:
        assert client.get('/api/v1/scans/'+scan['scan_id']+'/analysis', headers=auth()).status_code == 409
        assert client.post('/api/v1/scans/'+original_id+'/analysis/resource', headers=auth(),
                           json={'resource_id':scan['findings'][0]['resource_id'],'rule_id':'ORPHANED_DISK'}).status_code == 409
