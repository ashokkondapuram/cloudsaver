import json
from datetime import timedelta
from uuid import uuid4
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends,FastAPI,HTTPException
from fastapi.testclient import TestClient
from test_identity import build,workspace,OPERATOR,TID,SID,AWS
from identity.license_tokens import issue
from identity.domain import IdentityError
from app.offline_license import LicenseValidator

@pytest.fixture
def signed(tmp_path,monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    private=tmp_path/'private.pem';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));private.chmod(0o600)
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    for name,value in dict(PLATFORM_LICENSE_PRIVATE_KEY_FILE=str(private),PLATFORM_LICENSE_KEY_ID='local-v1',PLATFORM_LICENSE_ISSUER='https://platform.example',PLATFORM_LICENSE_AUDIENCE='cloudsaver',CLOUDSAVER_LICENSE_ISSUER='https://platform.example',CLOUDSAVER_LICENSE_AUDIENCE='cloudsaver',CLOUDSAVER_LICENSE_PUBLIC_KEYS=json.dumps({'local-v1':public}),CLOUDSAVER_AUTH_MODE='license',CLOUDSAVER_DIRECTORY_MODE='registry',CLOUDSAVER_ENVIRONMENT='test').items():monkeypatch.setenv(name,value)
    service=build();customer=workspace(service)
    payload=dict(name='Offline licence',roles=['Viewer'],all_providers=True,expires_at=(service.now()+timedelta(days=1)).isoformat())
    token=issue(service,TID,payload,OPERATOR)
    tenant=dict(tenant_id=TID,customer_id=customer['id'],name='Core workspace',subscription_ids=[SID],aws_accounts=AWS,roles=['TenantAdmin'],active=True,plan_tier='STARTER')
    return service,payload,token,tenant,key

def test_real_issue_verify_without_platform_or_network(signed,monkeypatch):
    service,_,issued,tenant,_=signed
    def unavailable(*args,**kwargs):raise AssertionError('Platform/network must not be consulted')
    service.store.transaction=unavailable
    monkeypatch.setattr(httpx.Client,'request',unavailable)
    monkeypatch.setattr(jwt,'PyJWKClient',unavailable)
    result=LicenseValidator().workspace(issued['token'],[tenant])
    assert result['roles']==['Viewer'] and result['plan_tier']=='ENTERPRISE'
    assert result['identity_provider']=='offline_license' and result['subject_type']=='license'
    assert result['licence_expires_at'] and not result.get('user_id')
    assert issued['scopes']['azure']==[SID]

@pytest.mark.parametrize('change',[{'exp':1},{'aud':'other'},{'iss':'other'},{'roles':['Root']},{'schema_version':True},{'nbf':4102444800},{'scopes':{'azure':['arbitrary']}},{'exp':4102444800}])
def test_invalid_signed_contracts_fail(signed,change):
    _,_,issued,tenant,key=signed
    claims=jwt.decode(issued['token'],options={'verify_signature':False});claims.update(change)
    token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'local-v1','typ':'cloudsaver-license+jwt'})
    with pytest.raises(HTTPException) as exc:LicenseValidator().workspace(token,[tenant])
    assert exc.value.status_code==401

def test_tampering_unknown_key_and_local_denylist(signed,monkeypatch):
    _,_,issued,tenant,key=signed
    claims=jwt.decode(issued['token'],options={'verify_signature':False})
    for token in [issued['token'][:-20]+'A'*20,jwt.encode(claims,key,algorithm='RS256',headers={'kid':'unknown','typ':'cloudsaver-license+jwt'})]:
        with pytest.raises(HTTPException):LicenseValidator().workspace(token,[tenant])
    monkeypatch.setenv('CLOUDSAVER_LICENSE_DENIED_IDS',json.dumps([issued['license_id']]))
    with pytest.raises(HTTPException):LicenseValidator().workspace(issued['token'],[tenant])

def test_scope_snapshot_does_not_expand(signed):
    _,_,issued,tenant,_=signed
    new=str(uuid4());tenant['subscription_ids'].append(new)
    result=LicenseValidator().workspace(issued['token'],[tenant])
    assert result['subscription_ids']==[SID] and result['scope_restrictions']['azure']==[SID]

def test_token_not_persisted_and_issuance_is_audited(signed):
    service,_,issued,_,_=signed
    assert issued['token'] not in repr(service.store.state)
    assert any(e['action']=='offline_license_issued' and e['details']['license_id']==issued['license_id'] for e in service.store.state['events'])

def test_operator_cannot_override_plan_or_issue_for_inactive_workspace(signed):
    service,payload,_,_,_=signed
    with pytest.raises(IdentityError):issue(service,TID,dict(payload,plan={'code':'ENTERPRISE'}),OPERATOR)
    service.set_workspace_status(TID,{'version':service.get_workspace(TID)['version']},'suspended',OPERATOR)
    with pytest.raises(IdentityError):issue(service,TID,payload,OPERATOR)

def test_auth_dependency_offline_mode(signed,monkeypatch):
    _,_,issued,tenant,_=signed
    from app.auth import tenant_dependency
    from app.config import Settings
    settings=Settings('azure',':memory:',(tenant,));app=FastAPI();dependency=tenant_dependency(settings)
    @app.get('/api/v1/me')
    def me(row=Depends(dependency)):return {'roles':row['roles'],'plan':row['plan_tier']}
    monkeypatch.setattr('app.identity_client.shared_client',lambda:(_ for _ in ()).throw(AssertionError('No platform client')))
    with TestClient(app) as client:
        assert client.get('/api/v1/me',headers={'Authorization':'Bearer '+issued['token']}).json()=={'roles':['Viewer'],'plan':'ENTERPRISE'}
        assert client.get('/api/v1/me',headers={'Authorization':'Bearer opaque-key'}).status_code==401

def test_operator_api_issue_is_authenticated_and_no_store(signed,monkeypatch):
    import hashlib,secrets
    from identity.app import create_app
    from identity.auth import OperatorAuth
    service,payload,_,tenant,_=signed
    caller=secrets.token_urlsafe(32);operator=secrets.token_urlsafe(32)
    monkeypatch.setenv('PLATFORM_OPERATOR_KEY_SHA256',hashlib.sha256(operator.encode()).hexdigest())
    app=create_app(service=service,callers={'portal':hashlib.sha256(caller.encode()).digest()},operator_auth=OperatorAuth(mode='operator_key',environment='development'))
    with TestClient(app) as client:
        url=f'/admin/v1/workspaces/{TID}/license-tokens'
        assert client.post(url,json=payload).status_code==401
        response=client.post(url,json=payload,headers={'X-Service-Token':caller,'Authorization':'Bearer '+operator})
        assert response.status_code==201
        assert response.headers['Cache-Control']=='no-store'
        assert LicenseValidator().workspace(response.json()['token'],[tenant])['roles']==['Viewer']


def test_platform_suspension_does_not_revoke_an_offline_snapshot(signed):
    service,_,issued,tenant,_=signed
    service.set_workspace_status(TID,{'version':service.get_workspace(TID)['version']},'suspended',OPERATOR)
    assert LicenseValidator().workspace(issued['token'],[tenant])['roles']==['Viewer']
    tenant['active']=False
    with pytest.raises(HTTPException) as exc:LicenseValidator().workspace(issued['token'],[tenant])
    assert exc.value.status_code==403


def test_background_grant_fails_closed_and_expires_locally(signed,monkeypatch):
    _,_,issued,tenant,_=signed
    from app.keycloak import current_licence
    monkeypatch.setenv('CLOUDSAVER_BACKGROUND_LICENSES','{}')
    with pytest.raises(HTTPException):current_licence(tenant)
    monkeypatch.setenv('CLOUDSAVER_BACKGROUND_LICENSES',json.dumps({TID:issued['token']}))
    assert current_licence(tenant)['plan_tier']=='ENTERPRISE'
    monkeypatch.setenv('CLOUDSAVER_LICENSE_DENIED_IDS',json.dumps([issued['license_id']]))
    with pytest.raises(HTTPException):current_licence(tenant)

def test_readiness_checks_local_trust_without_platform(signed,monkeypatch):
    _,_,_,tenant,_=signed
    from services.common import service
    from app.config import Settings
    app,_,_=service('offline-check',Settings('azure',':memory:',(tenant,)))
    with TestClient(app) as client:
        assert client.get('/health/ready').status_code==200
        monkeypatch.setenv('CLOUDSAVER_LICENSE_PUBLIC_KEYS','{}')
        assert client.get('/health/ready').status_code==503
        assert client.get('/health/live').status_code==200
