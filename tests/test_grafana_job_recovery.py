from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
import pytest
from app.collectors import grafana_rightsizing as gk
from app.grafana_k8s_store import GrafanaK8sStore
from app.v150_store import WorkflowConflict
from tests.test_enterprise import evidence, workspace

def new_job(store):
    repo=GrafanaK8sStore(store)
    tenant=workspace()
    c=repo.connectors.create(tenant,dict(name='G-'+str(uuid4()),kind='grafana_mimir',base_url='https://grafana.example.com/',
        auth_kind='none',mimir_datasource_uid='mimir',cluster_values=['dev'],cluster_label='cluster',schedule='manual'))
    return repo,tenant,repo.submit(tenant,str(uuid4()),c['id'])

def test_normal_worker_selection_recovers_abandoned_job(evidence,monkeypatch):
    _,store,_=evidence
    repo,tenant,job=new_job(store)
    repo._claim(tenant['tenant_id'],job['id'],worker_id='crashed')
    with store.transaction(tenant['tenant_id'],write=True) as db:
        db.execute('UPDATE observability_jobs SET lease_until=%s WHERE tenant_id=%s AND id=%s',
                   ((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),tenant['tenant_id'],job['id']))
    monkeypatch.setattr(gk,'run_rightsizing',lambda *a,**kw:dict(items=[]))
    recovered=repo.claim_next(tenant['tenant_id'],worker_id='replacement')
    assert recovered['status']=='completed'
    assert [a['state'] for a in recovered['payload']['attempts']]==['abandoned','completed']

def test_expired_owner_cannot_publish_success(evidence,monkeypatch):
    _,store,_=evidence
    repo,tenant,job=new_job(store)
    def expire(*args,**kwargs):
        with store.transaction(tenant['tenant_id'],write=True) as db:
            db.execute('UPDATE observability_jobs SET lease_until=%s WHERE tenant_id=%s AND id=%s',
                       ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),tenant['tenant_id'],job['id']))
        return dict(items=[])
    monkeypatch.setattr(gk,'run_rightsizing',expire)
    with pytest.raises(WorkflowConflict,match='lease was lost'):
        repo.process_job(tenant,job['id'])
    assert repo.job(tenant['tenant_id'],job['id'])['status']=='running'

def test_legacy_public_error_is_sanitized():
    row=(str(uuid4()),'failed',dict(error='https://host/?secret=token'), 'now','now')
    payload=GrafanaK8sStore._job(row)['payload']
    assert 'secret' not in json.dumps(payload)
    assert payload['error']['error_code']=='GRAFANA_QUERY_FAILED'

def test_heartbeat_requires_unexpired_ownership(evidence):
    _,store,_=evidence
    repo,tenant,job=new_job(store)
    tid=tenant['tenant_id']
    claim=repo._claim(tid,job['id'],worker_id='owner')
    deadline=datetime.fromisoformat(claim['payload']['deadline_at'])
    assert repo._heartbeat(tid,job['id'],claim['token'],deadline)
    with store.transaction(tid,write=True) as db:
        db.execute('UPDATE observability_jobs SET lease_until=%s WHERE tenant_id=%s AND id=%s',
                   ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),tid,job['id']))
    assert not repo._heartbeat(tid,job['id'],claim['token'],deadline)

def test_late_result_is_expired_not_completed(evidence,monkeypatch):
    import app.grafana_k8s_store as jobs
    _,store,_=evidence
    repo,tenant,job=new_job(store)
    def late(*args,**kwargs):
        after=kwargs['deadline_at']+timedelta(seconds=1)
        monkeypatch.setattr(jobs,'_now',lambda:after)
        return dict(items=[])
    monkeypatch.setattr(gk,'run_rightsizing',late)
    result=repo.process_job(tenant,job['id'])
    assert result['status']=='expired'
    assert 'result' not in result['payload']

def test_provider_exception_is_not_logged(evidence,monkeypatch,caplog):
    _,store,_=evidence
    repo,tenant,job=new_job(store)
    def fail(*args,**kwargs):
        raise RuntimeError('https://host/?secret=private-value')
    monkeypatch.setattr(gk,'run_rightsizing',fail)
    result=repo.process_job(tenant,job['id'])
    assert result['status']=='failed'
    assert 'private-value' not in caplog.text
    assert 'private-value' not in json.dumps(result)
