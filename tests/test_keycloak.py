import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.entitlements import TIER_LIMITS, PlanTier, entitlements_for
from app.keycloak import Binding, KeycloakValidator, bindings

TID, UID, GROUP, CLIENT = [str(uuid4()) for _ in range(4)]
ISSUER='https://identity.example/realms/customer'


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KEYCLOAK_SECRET_TEST','synthetic-local-test-secret')
    binding=Binding(tenant_id=TID,issuer=ISSUER,audience='cloudsaver-api',client_id='verifier',
        client_uuid=CLIENT,secret_env='CLOUDSAVER_KEYCLOAK_SECRET_TEST',group_id=GROUP,authorized_parties=['console'])
    licence=dict(schema_version=1,enabled=True,expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
        plan=dict(code='GROWTH',entitlements=TIER_LIMITS[PlanTier.GROWTH].model_dump()))
    state=dict(active=True,user_enabled=True,roles=['Viewer'],groups=[{'id':GROUP}],licence=licence,status=200,service=False)
    calls=[]
    def respond(request):
        calls.append(request)
        assert request.url.host=='identity.example'
        path=request.url.path
        if state['status']!=200:return httpx.Response(state['status'],text='sensitive provider error')
        if path.endswith('/introspect'):
            assert parse_qs(request.content.decode())['client_secret']==['synthetic-local-test-secret']
            return httpx.Response(200,json={'active':state['active'],'sub':UID})
        if path.endswith('/token'):return httpx.Response(200,json={'access_token':'admin-token','expires_in':60})
        assert request.headers['authorization']=='Bearer admin-token'
        if path.endswith('/users/'+UID):return httpx.Response(200,json={'id':UID,'enabled':state['user_enabled'],**({'serviceAccountClientId':'collector'} if state['service'] else {})})
        if path.endswith('/users/'+UID+'/groups'):return httpx.Response(200,json=state['groups'])
        if path.endswith('/composite'):return httpx.Response(200,json=[{'name':role} for role in state['roles']])
        if path.endswith('/groups/'+GROUP):return httpx.Response(200,json={'id':GROUP,'attributes':{'cloudsaver_license':[json.dumps(state['licence'])]}})
        pytest.fail('Unexpected identity operation')
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=int(time.time())
    claims=dict(iss=ISSUER,aud='cloudsaver-api',sub=UID,iat=now,exp=now+300,azp='console',typ='Bearer',cloudsaver_tenant_id=TID,
                realm_access={'roles':['TenantAdmin']},plan={'code':'ENTERPRISE'})
    encode=lambda c:jwt.encode(c,key,algorithm='RS256',headers={'kid':'test'})
    validator=KeycloakValidator({TID:binding},key_resolver=lambda *_:key.public_key(),transport=httpx.MockTransport(respond))
    tenant=dict(tenant_id=TID,active=True,subscription_ids=[],roles=['TenantAdmin'],plan_tier='ENTERPRISE')
    return validator,claims,encode,tenant,state,calls,binding


def test_live_roles_and_licence_replace_untrusted_token_and_registry_values(identity):
    validator,claims,encode,tenant,state,calls,_=identity
    token=encode(claims)
    result=validator.workspace(token,[tenant])
    assert result['roles']==['Viewer'] and result['plan_tier']=='GROWTH'
    assert result['user_id']==UID and result['subject_type']=='user'
    assert entitlements_for(result).source=='keycloak'
    state['roles']=['BillingAdmin']
    assert validator.workspace(token,[tenant])['roles']==['BillingAdmin']
    assert len([r for r in calls if r.url.path.endswith('/token')])==1
    assert len([r for r in calls if r.url.path.endswith('/groups/'+GROUP)])==2
    assert 'synthetic-local-test-secret' not in json.dumps(result)


@pytest.mark.parametrize('field,value,status',[
    ('active',False,401),('user_enabled',False,403),('groups',[],403),('roles',[],403),('status',503,503),
])
def test_current_revocation_and_identity_outage_fail_closed(identity,field,value,status):
    validator,claims,encode,tenant,state,_,_=identity
    validator.workspace(encode(claims),[tenant]);state[field]=value
    with pytest.raises(HTTPException) as exc:validator.workspace(encode(claims),[tenant])
    assert exc.value.status_code==status and 'sensitive' not in str(exc.value.detail)


@pytest.mark.parametrize('change',[
    {'aud':'wrong'}, {'iss':'https://attacker.example/realms/customer'}, {'azp':'other'}, {'cloudsaver_tenant_id':str(uuid4())},
    {'typ':'ID'}, {'exp':1}, {'iat':0}, {'sub':'not-an-id'}, {'exp':int(time.time())+900},
])
def test_invalid_tokens_never_select_arbitrary_endpoints(identity,change):
    validator,claims,encode,tenant,_,calls,_=identity
    claims.update(change)
    with pytest.raises(HTTPException) as exc:validator.workspace(encode(claims),[tenant])
    assert exc.value.status_code==401 and calls==[]


@pytest.mark.parametrize('change,status',[
    ({'enabled':False},403),({'expires_at':'2020-01-01T00:00:00Z'},403),({'expires_at':'2030-01-01'},503),
    ({'schema_version':True},503),({'enabled':'true'},503),({'plan':None},503),({'unexpected':True},503),
])
def test_bad_or_expired_licence_never_falls_back_to_registry_plan(identity,change,status):
    validator,claims,encode,tenant,state,_,_=identity
    state['licence'].update(change)
    for run in (lambda:validator.workspace(encode(claims),[tenant]),lambda:validator.licensed_workspace(tenant)):
        with pytest.raises(HTTPException) as exc:run()
        assert exc.value.status_code==status


def test_service_account_is_not_a_human_approver(identity):
    validator,claims,encode,tenant,state,_,_=identity
    state['service']=True
    result=validator.workspace(encode(claims),[tenant])
    assert result['subject_type']=='service_account' and 'user_id' not in result


def test_tenants_cannot_share_the_same_client_role_namespace(identity,monkeypatch):
    binding=identity[-1].model_dump()
    monkeypatch.setenv('CLOUDSAVER_KEYCLOAK_BINDINGS',json.dumps([binding,dict(binding,tenant_id=str(uuid4()),group_id=str(uuid4()))]))
    with pytest.raises(ValueError):bindings()


def test_azure_identity_is_independent_of_keycloak_workspace(monkeypatch):
    from app.tenant_config import normalize_identity
    azure=str(uuid4())
    assert normalize_identity({'azure_tenant_id':azure})=={'azure_tenant_id':azure}
    with pytest.raises(ValueError):normalize_identity({'azure_tenant_id':'invalid'})


def test_keycloak_mode_is_used_by_the_api_and_does_not_accept_legacy_keys(identity,monkeypatch,tmp_path):
    import hashlib
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    validator,claims,encode,tenant,state,_,_=identity
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','keycloak')
    tenant=dict(tenant,name='Client',api_key_sha256=hashlib.sha256(b'x'*40).hexdigest())
    settings=Settings('azure',str(tmp_path/'keycloak.sqlite3'),(tenant,))
    with TestClient(create_app(settings,identity_validator=validator)) as client:
        headers={'Authorization':'Bearer '+encode(claims)}
        response=client.get('/api/v1/me',headers=headers)
        assert response.status_code==200
        assert response.json()['identity_provider']=='keycloak' and response.json()['roles']==['Viewer']
        assert client.get('/api/v1/me',headers={'Authorization':'Bearer '+'x'*40}).status_code==401
        state['active']=False
        assert client.get('/api/v1/me',headers=headers).status_code==401


def test_worker_licence_expiry_blocks_collection_before_the_scanner(identity,monkeypatch):
    from types import SimpleNamespace
    from workers.tasks import authorized_tenant
    validator,_,_,tenant,state,_,_=identity
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE','keycloak')
    monkeypatch.setattr('app.keycloak.background_validator',lambda:validator)
    state['licence']['enabled']=False
    with pytest.raises(HTTPException) as exc:
        authorized_tenant(SimpleNamespace(tenants=[tenant]),None,TID,[])
    assert exc.value.status_code==403
