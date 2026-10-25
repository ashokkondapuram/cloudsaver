"""GitHub effects are simulated; no real branch or pull request is created."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
import httpx
import jwt
import pytest

from app.config import Settings
from app.gitops import GitHubApp,GitOpsConfig,GitOpsFailure,build_review
from app.gitops_store import ReviewConflict,ReviewRepository
from app.main import create_app
from app.store import Store

TENANT='11111111-1111-4111-8111-111111111111'
SUB='22222222-2222-4222-8222-222222222222'
KEY='test-gitops-key-with-at-least-32-characters'  # gitleaks:allow -- fixed public synthetic test constant
TARGET=dict(tenant_id=TENANT,target_id='infra',repository='example/infra',repository_id=123,base_branch='main',installation_id=456)


def workspace():
    return dict(tenant_id=TENANT,name='GitOps workspace',subscription_ids=[SUB],plan_tier='GROWTH',api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())


def snapshot():
    finding=dict(rule_id='ORPHANED_DISK',severity='HIGH',resource_name='archive',resource_type='Microsoft.Compute/disks',
        resource_group='test',subscription_id=SUB,resource_id=f'/subscriptions/{SUB}/resourceGroups/test/providers/Microsoft.Compute/disks/archive',
        details='Review retention',estimated_monthly_waste_usd=None)
    return dict(scan_id=str(uuid4()),timestamp=datetime.now(timezone.utc).isoformat(),mode='azure',status='completed',
                subscriptions_scanned=1,total_items_found=1,total_monthly_waste_usd=None,findings=[finding])


def package():
    scan=snapshot()
    return build_review(scan,[scan['findings'][0]['resource_id']],workspace(),TARGET)


def test_package_determinism_scope_and_review_only_files():
    scan=snapshot();ids=[scan['findings'][0]['resource_id']]
    first=build_review(scan,ids,workspace(),TARGET)
    assert first==build_review(scan,ids,workspace(),TARGET)
    assert all(p.startswith('.cloudsaver/reviews/'+first['review_id']+'/') for p in first['files'])
    assert first['draft'] is True and first['branch'].startswith('cloudsaver/review-')
    hcl=next(v for k,v in first['files'].items() if k.endswith('.tf'))
    assert 'import {' in hcl and 'resource "' not in hcl and 'destroy' not in hcl
    with pytest.raises(ValueError):build_review(dict(scan,mode='demo'),ids,workspace(),TARGET)
    with pytest.raises(ValueError):build_review(scan,ids,workspace(),dict(TARGET,tenant_id=str(uuid4())))
    with pytest.raises(ValueError):build_review(dict(scan,data_origin='legacy_synthetic'),ids,workspace(),TARGET)


class GitHub:
    def __init__(self,package,public_key,*,wrong_repository=False,prior=False,collision=False,timeout=False,tampered=False):
        self.package,self.public_key=package,public_key
        self.wrong_repository,self.prior,self.collision,self.timeout=wrong_repository,prior,collision,timeout
        self.tampered=tampered
        self.calls=[]
    def pull(self):
        return dict(number=7,html_url='https://github.com/example/infra/pull/7',state='open',draft=True,
            head={'ref':self.package['branch'],'repo':{'id':123},'sha':'d'*40},base={'ref':'main','repo':{'id':123}},body=self.package['body'])
    def __call__(self,request):
        self.calls.append(request)
        path,method=request.url.path,request.method
        if path=='/app/installations/456/access_tokens':
            claims=jwt.decode(request.headers['authorization'][7:],self.public_key,algorithms=['RS256'])
            assert claims['iss']=='789' and 0<claims['exp']-claims['iat']<=600
            assert json.loads(request.content)=={'repository_ids':[123],'permissions':{'contents':'write','pull_requests':'write'}}
            return httpx.Response(201,json=dict(token='installation-secret-never-persist',expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
        assert request.headers['authorization']=='Bearer installation-secret-never-persist'
        if path=='/repos/example/infra':
            return httpx.Response(200,json=dict(id=999 if self.wrong_repository else 123,full_name='example/infra',archived=False))
        if '/contents/' in path:
            name=path.split('/contents/',1)[1]
            raw=self.package['files'][name].encode()
            return httpx.Response(200,json={'type':'file','sha':'f'*40 if self.tampered else hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()})
        if path.endswith('/pulls'):
            if method=='GET':return httpx.Response(200,json=[self.pull()] if self.prior else [])
            payload=json.loads(request.content)
            assert payload['draft'] is True and payload['base']=='main' and payload['head']==self.package['branch']
            self.prior=True
            if self.timeout:
                self.timeout=False
                raise httpx.ReadTimeout('response lost after GitHub accepted the PR',request=request)
            return httpx.Response(201,json=self.pull())
        if '/git/ref/heads/' in path:return httpx.Response(200,json={'object':{'sha':('a' if path.endswith('/main') else 'e')*40}})
        if path.endswith('/git/commits/'+'a'*40):return httpx.Response(200,json={'tree':{'sha':'b'*40}})
        if path.endswith('/git/commits/'+'e'*40):return httpx.Response(200,json={'tree':{'sha':'f'*40}})
        if path.endswith('/git/trees'):
            payload=json.loads(request.content)
            assert payload['base_tree']=='b'*40
            assert {r['path']:r['content'] for r in payload['tree']}==self.package['files']
            return httpx.Response(201,json={'sha':'c'*40})
        if path.endswith('/git/commits'):
            assert json.loads(request.content)['parents']==['a'*40]
            return httpx.Response(201,json={'sha':'d'*40})
        if path.endswith('/git/refs'):return httpx.Response(422 if self.collision else 201,json={})
        raise AssertionError('Unexpected GitHub operation: '+str(request.url))


@pytest.fixture
def signing_key():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    return key,pem


def test_github_app_creates_atomic_isolated_draft_and_reconciles_retry(signing_key):
    key,pem=signing_key;bundle=package();remote=GitHub(bundle,key.public_key())
    adapter=GitHubApp('789',private_key=pem,transport=httpx.MockTransport(remote))
    result=adapter.publish(TARGET,bundle)
    assert result['pr_url']=='https://github.com/example/infra/pull/7' and result['draft'] is True
    assert adapter.publish(TARGET,bundle)==result
    assert sum(r.method=='POST' and r.url.path.endswith('/pulls') for r in remote.calls)==1
    assert all(r.method not in ('PATCH','DELETE','PUT') for r in remote.calls)
    assert 'installation-secret' not in json.dumps(result)


def test_github_lost_response_recovers_existing_pr_without_duplicate(signing_key):
    key,pem=signing_key;bundle=package();remote=GitHub(bundle,key.public_key(),timeout=True)
    adapter=GitHubApp('789',private_key=pem,transport=httpx.MockTransport(remote))
    with pytest.raises(GitOpsFailure):adapter.publish(TARGET,bundle)
    assert adapter.publish(TARGET,bundle)['pr_number']==7
    assert sum(r.method=='POST' and r.url.path.endswith('/pulls') for r in remote.calls)==1


def test_github_refuses_wrong_repo_and_different_existing_branch(signing_key):
    key,pem=signing_key
    for options in [dict(wrong_repository=True),dict(collision=True)]:
        bundle=package();remote=GitHub(bundle,key.public_key(),**options)
        with pytest.raises(GitOpsFailure):GitHubApp('789',private_key=pem,transport=httpx.MockTransport(remote)).publish(TARGET,bundle)
        assert not any(r.method=='POST' and r.url.path.endswith('/pulls') for r in remote.calls)
        assert not any(r.method=='PATCH' for r in remote.calls)
        if options.get('collision'):
            assert any(r.method=='POST' and r.url.path.endswith('/git/refs') for r in remote.calls)


def test_github_redirect_never_follows_untrusted_destination(signing_key):
    _,pem=signing_key
    with pytest.raises(GitOpsFailure):
        GitHubApp('789',private_key=pem,transport=httpx.MockTransport(lambda _:httpx.Response(302,headers={'location':'https://evil.example'}))).publish(TARGET,package())


def test_existing_pr_files_must_match_the_preview(signing_key):
    key,pem=signing_key;bundle=package();remote=GitHub(bundle,key.public_key(),prior=True,tampered=True)
    with pytest.raises(GitOpsFailure,match='differ'):
        GitHubApp('789',private_key=pem,transport=httpx.MockTransport(remote)).publish(TARGET,bundle)
    assert not any(r.method=='POST' and '/repos/' in r.url.path for r in remote.calls)


def test_sqlite_request_keys_restart_leases_and_fencing(tmp_path):
    store=Store(str(tmp_path/'history.sqlite'));scan=snapshot();store.save(TENANT,scan,workspace=workspace())
    repo=ReviewRepository(store);bundle=build_review(scan,[scan['findings'][0]['resource_id']],workspace(),TARGET)
    id=repo.reserve(TENANT,'a-long-idempotency-key',bundle)
    assert repo.reserve(TENANT,'a-long-idempotency-key',bundle)==id
    with pytest.raises(ReviewConflict):repo.reserve(TENANT,'a-long-idempotency-key',dict(bundle,fingerprint='changed'))
    old,new=str(uuid4()),str(uuid4())
    assert repo.claim(TENANT,id,old)
    with pytest.raises(ReviewConflict):repo.claim(TENANT,id,new)
    with store.connection() as db:db.execute('UPDATE gitops_requests SET lease_until=0 WHERE id=?',(id,))
    assert repo.claim(TENANT,id,new)
    with pytest.raises(ReviewConflict):repo.finish(TENANT,id,old,{'pr_number':7})
    repo.finish(TENANT,id,new,{'pr_number':7})
    assert not repo.claim(TENANT,id,str(uuid4()))
    restarted=ReviewRepository(Store(str(tmp_path/'history.sqlite')))
    assert restarted.get(TENANT,id)['status']=='open'
    assert restarted.get(str(uuid4()),id) is None


class Publisher:
    def __init__(self,fail_first=False):self.calls,self.fail_first=0,fail_first
    def publish(self,target,bundle):
        self.calls+=1
        if self.fail_first and self.calls==1:raise GitOpsFailure('private GitHub failure')
        return dict(pr_url='https://github.com/example/infra/pull/7',pr_number=7,state='open',draft=True)


@pytest.mark.parametrize('fail_first',[False,True])
def test_api_preview_publish_idempotency_and_uncertain_history(tmp_path,fail_first):
    scan=snapshot();settings=Settings('azure',str(tmp_path/'api.sqlite'),(workspace(),))
    auth={'Authorization':'Bearer '+KEY};publisher=Publisher(fail_first)
    with TestClient(create_app(settings,scanner=lambda _:deepcopy(scan['findings']),gitops_config=GitOpsConfig((TARGET,),True,'789'),gitops_client=publisher)) as client:
        saved=client.post('/api/v1/scans',headers=auth).json()
        selection=dict(scan_id=saved['scan_id'],target_id='infra',resource_ids=[saved['findings'][0]['resource_id']])
        assert client.post('/api/v1/gitops/preview',headers=auth,json=selection).status_code==200
        assert publisher.calls==0
        selection['idempotency_key']='test-request-key-1234'
        if fail_first:
            failed=client.post('/api/v1/gitops/requests',headers=auth,json=selection)
            assert failed.status_code==502 and 'private' not in failed.text
            assert client.get('/api/v1/gitops/requests',headers=auth).json()[0]['status']=='uncertain'
        first=client.post('/api/v1/gitops/requests',headers=auth,json=selection)
        assert first.status_code==201 and first.json()['status']=='open'
        assert client.post('/api/v1/gitops/requests',headers=auth,json=selection).json()==first.json()
        assert publisher.calls==(2 if fail_first else 1)
        assert client.get('/api/v1/gitops/requests',headers=auth).json()[0]['result']['pr_number']==7
        assert client.get('/api/v1/gitops/requests/'+str(uuid4()),headers=auth).status_code==404
    with TestClient(create_app(settings,gitops_config=GitOpsConfig((TARGET,),False))) as client:
        assert client.post('/api/v1/gitops/requests',headers=auth,json=selection).status_code==503


def test_config_is_operator_owned_and_no_arbitrary_endpoints(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_GITOPS_TARGETS',json.dumps([TARGET]))
    assert GitOpsConfig.load().target(TENANT,'infra')==TARGET
    with pytest.raises(ValueError):GitOpsConfig.load().target(str(uuid4()),'infra')
    monkeypatch.setenv('CLOUDSAVER_GITOPS_TARGETS',json.dumps([TARGET|{'base_branch':'../../main'}]))
    with pytest.raises(ValueError):GitOpsConfig.load()


def test_legacy_synthetic_history_never_becomes_live_export_evidence(tmp_path):
    from app.remediation import generate_script
    store=Store(str(tmp_path/'legacy.sqlite'))
    legacy=snapshot();legacy.update(mode='demo',total_monthly_waste_usd=999)
    with store.connection() as db:
        db.execute('INSERT INTO scans VALUES (?,?,?,?)',(legacy['scan_id'],TENANT,legacy['timestamp'],json.dumps(legacy)))
    read=store.get(TENANT,legacy['scan_id'])
    assert read['data_origin']=='legacy_synthetic' and read['total_monthly_waste_usd'] is None
    assert read['scope_fingerprint'] is None
    assert read['findings'][0]['estimated_monthly_waste_usd'] is None
    ids=[read['findings'][0]['resource_id']]
    with pytest.raises(ValueError):build_review(read,ids,workspace(),TARGET)
    with pytest.raises(ValueError):generate_script(read,ids,TENANT,[SUB])
    with store.connection() as db:
        assert json.loads(db.execute('SELECT payload FROM scans').fetchone()[0])['mode']=='demo'
