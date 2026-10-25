"""Launch-blocking gateway/auth/billing contracts, using synthetic credentials only."""
import json
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from services.gateway import create_app
from tests.test_services import configuration,Limiter,KEY


@pytest.mark.parametrize('path',[
    '/api/v1/gitops/preview','/api/v1/gitops/requests','/api/v1/policies/terraform/evaluate',
    '/api/v1/scans/44444444-4444-4444-8444-444444444444/analysis/resource',
    '/api/v1/scans/44444444-4444-4444-8444-444444444444/ai-risk-evaluation'])
def test_gateway_post_contract_preserves_destination_body_auth_and_correlation(tmp_path,path):
    seen=[];body={'synthetic':'exact JSON','nested':{'number':2}}
    rid=str(uuid4())
    def core(request):
        seen.append(request)
        assert str(request.url)=='http://scanner-service:8002'+path
        assert json.loads(request.content)==body
        assert request.headers['authorization']=='Bearer '+KEY
        assert request.headers['x-request-id']==rid
        return httpx.Response(200,json={'forwarded':True})
    api=TestClient(create_app(configuration(tmp_path),Limiter(),httpx.MockTransport(core)))
    r=api.post(path,json=body,headers={'Authorization':'Bearer '+KEY,'X-Request-ID':rid})
    assert r.status_code in (200,201),r.text
    assert r.json()=={'forwarded':True} and len(seen)==1


def test_billing_summary_get_never_synchronizes_or_writes(tmp_path,monkeypatch):
    from app.main import create_app as core
    from app.collectors import billing_sync
    from app.enterprise_store import EnterpriseStore
    from tests.test_services import TID,SID
    settings=configuration(tmp_path)
    monkeypatch.setenv('CLOUDSAVER_BILLING_CONNECTORS',json.dumps([dict(tenant_id=TID,provider='azure',scope_id=SID)]))
    def forbidden(*a,**k):raise AssertionError('A GET must never invoke ingestion')
    monkeypatch.setattr(billing_sync,'sync_workspace_billing',forbidden)
    api=TestClient(core(settings))
    for _ in range(3):
        r=api.get('/api/v1/finops/summary',headers={'Authorization':'Bearer '+KEY})
        assert r.status_code==200,r.text
    store=EnterpriseStore(settings)
    with store.transaction(TID) as db:
        for table in ('focus_imports','focus_charges','billing_sync_runs'):
            assert db.execute(f'SELECT count(*) FROM {table} WHERE tenant_id=%s',(TID,)).fetchone()[0]==0


def production(monkeypatch):
    for k,v in dict(CLOUDSAVER_ENVIRONMENT='production',CLOUDSAVER_KEY_VERIFIER='identity',CLOUDSAVER_DIRECTORY_MODE='cutover',CLOUDSAVER_TENANT_REGISTRY='database',CLOUDSAVER_CLOUD_IDENTITY='managed_identity',CLOUDSAVER_INSTALL_AZURE_CLI='false',CLOUDSAVER_AUTH_MODE='workspace').items():monkeypatch.setenv(k,v)

@pytest.mark.parametrize('name,value',[
    ('CLOUDSAVER_KEY_VERIFIER','local'),('CLOUDSAVER_KEY_VERIFIER','shadow'),('CLOUDSAVER_DIRECTORY_MODE','registry'),
    ('CLOUDSAVER_TENANT_REGISTRY','env'),('CLOUDSAVER_CLOUD_IDENTITY','developer'),('CLOUDSAVER_INSTALL_AZURE_CLI','true'),
    ('CLOUDSAVER_AGENT_AZURE_IDENTITY','developer'),('CLOUDSAVER_AUTH_MODE','unknown')])
def test_production_profile_rejects_unsafe_configuration(monkeypatch,name,value):
    from app.config import validate_production
    production(monkeypatch);monkeypatch.setenv(name,value)
    with pytest.raises(ValueError):validate_production('postgresql://synthetic-not-used/db')


def test_production_requires_database_and_explicit_entra_policy(monkeypatch):
    from app.config import validate_production
    production(monkeypatch)
    with pytest.raises(ValueError):validate_production(None)
    validate_production('postgresql://synthetic-not-used/db')
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra')
    with pytest.raises(ValueError):validate_production('postgresql://synthetic-not-used/db')
    monkeypatch.setenv('CLOUDSAVER_ENTRA_ACCESS_POLICY','tenant_roles');monkeypatch.setenv('CLOUDSAVER_ENTRA_AUDIENCE','api://reviewed')
    validate_production('postgresql://synthetic-not-used/db')


def test_configured_cors_supports_intended_writes_and_denies_unapproved_origin(tmp_path,monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ALLOWED_ORIGINS','https://console.example')
    api=TestClient(create_app(configuration(tmp_path),Limiter(),httpx.MockTransport(lambda r:httpx.Response(200,json={}))))
    for method in ('PUT','PATCH'):
        r=api.options('/api/v1/settings',headers={'Origin':'https://console.example','Access-Control-Request-Method':method,'Access-Control-Request-Headers':'authorization,content-type'})
        assert r.status_code==200 and r.headers['access-control-allow-origin']=='https://console.example'
    assert api.options('/api/v1/settings',headers={'Origin':'https://console.example','Access-Control-Request-Method':'TRACE'}).status_code==400
    r=api.options('/api/v1/settings',headers={'Origin':'https://evil.example','Access-Control-Request-Method':'PUT'})
    assert r.status_code==400 and 'access-control-allow-origin' not in r.headers


def test_entra_mode_enforces_shared_product_suspension_policy(tmp_path,monkeypatch):
    from app.auth import UserClaims,Role
    from app.main import create_app as core
    from tests.test_services import TID
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','entra')
    monkeypatch.setattr('app.auth.with_plan',lambda settings,row:dict(row,plan={'access_suspended':True}))
    class Human:
        def verify_token(self,value):return UserClaims(user_id=str(uuid4()),tenant_id=TID,roles=[Role.VIEWER])
    api=TestClient(core(configuration(tmp_path),identity_validator=Human()))
    assert api.get('/api/v1/scans',headers={'Authorization':'Bearer synthetic-human'}).status_code==403
    assert api.get('/api/v1/me',headers={'Authorization':'Bearer synthetic-human'}).status_code==200


def test_stale_production_projection_denies_authorization(monkeypatch):
    from types import SimpleNamespace
    from app.config import require_directory_freshness
    production(monkeypatch)
    for lag in (None,31):
        with pytest.raises(RuntimeError):require_directory_freshness(SimpleNamespace(registry=SimpleNamespace(projection_lag_seconds=lambda:lag)))
    require_directory_freshness(SimpleNamespace(registry=SimpleNamespace(projection_lag_seconds=lambda:1)))
