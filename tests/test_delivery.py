"""Fault-focused delivery tests; all remote calls use an HTTP mock transport."""
import json
from types import SimpleNamespace

import httpx
import pytest

from app.delivery_config import Target,load_targets
from workers.dispatcher import dispatch_one,retry_after,main

TENANT='11111111-1111-4111-8111-111111111111'
TARGET=Target('finops',TENANT,'slack','https://hooks.slack.com/services/T/B/test-secret')


class Repository:
    def __init__(self,kind='notification',attempts=1):
        self.event={'id':'event-1','kind':kind,'job_id':'job-1','scan_id':'scan-1','target_id':'finops',
                    'target_fingerprint':TARGET.fingerprint,'payload':{'findings_count':7,'scopes_count':2},
                    'lease_token':'token','attempts':attempts}
        self.result=None
    def claim(self,tenant,kinds):
        assert tenant==TENANT
        return self.event if self.event['kind'] in kinds else None
    def finish(self,tenant,event,**result):
        self.result=result
        return True


def send(repository,handler,**kwargs):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return dispatch_one(repository,TENANT,targets=(TARGET,),publish_scan=lambda *_:None,client=client,**kwargs)


@pytest.mark.parametrize('status,outcome,code',[(200,'delivered',None),(204,'delivered',None),
    (301,'dead_letter','provider_rejected'),(401,'dead_letter','provider_rejected'),
    (408,'retry','provider_unavailable'),(429,'retry','rate_limited'),(503,'retry','provider_unavailable')])
def test_response_classification_and_secret_free_envelopes(status,outcome,code):
    repository=Repository()
    def handler(request):
        assert request.headers['X-CloudSaver-Event-ID']=='event-1'
        assert 'authorization' not in request.headers
        body=json.loads(request.content)
        assert body['blocks'][0]['text']['type']=='plain_text'
        assert '7 review findings across 2 scopes' in body['text']
        assert b'job-1' not in request.content and b'test-secret' not in request.content
        return httpx.Response(status,headers={'Retry-After':'120','Location':'http://127.0.0.1/private'},text='private-provider-response')
    assert send(repository,handler)
    assert repository.result['outcome']==outcome and repository.result['error_code']==code
    if status==429:
        assert repository.result['retry_after']==120
    assert 'private' not in str(repository.result) and 'secret' not in str(repository.result)


def test_lost_response_keeps_retryable_delivery_and_does_not_store_exception():
    repository=Repository()
    def handler(request):
        raise httpx.ReadTimeout('private URL and credential',request=request)
    send(repository,handler)
    assert repository.result['outcome']=='retry'
    assert 'private' not in str(repository.result)


def test_changed_destination_is_never_silently_used():
    repository=Repository()
    repository.event['target_fingerprint']='changed'
    send(repository,lambda _:pytest.fail('Changed destination was used'))
    assert repository.result['outcome']=='dead_letter' and repository.result['error_code']=='target_changed'


def test_scan_publish_failure_and_scope_recheck():
    repository=Repository(kind='scan')
    repository.event['payload']={'subscription_ids':['sub']}
    with httpx.Client() as client:
        def failed(*_):
            raise ConnectionError('redis://private:password@host')
        dispatch_one(repository,TENANT,targets=(),publish_scan=failed,client=client)
        assert repository.result['outcome']=='retry' and 'password' not in str(repository.result)
        dispatch_one(repository,TENANT,targets=(),publish_scan=lambda *_:pytest.fail('Revoked scope published'),
                     client=client,authorize_scan=lambda *_:False)
        assert repository.result['error_code']=='scope_revoked'


def test_teams_uses_adaptive_card_without_slack_envelope():
    from workers.dispatcher import notification_message
    target=Target('teams',TENANT,'teams','https://example.webhook.office.com/path')
    payload=notification_message(Repository().event,target)
    card=payload['attachments'][0]['content']
    assert card['type']=='AdaptiveCard' and card['body'][0]['wrap'] is True
    assert 'blocks' not in payload


@pytest.mark.parametrize('value,expected',[(None,60),('nonsense',60),('inf',60),('NaN',60),('-10',1),('999999',3600),('123',123)])
def test_retry_after_is_bounded(value,expected):
    assert retry_after(value)==expected


def test_disabled_dispatcher_creates_no_clients(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_DELIVERY_ENABLED',raising=False)
    monkeypatch.setattr('app.config.Settings.load',lambda:pytest.fail('Disabled process loaded runtime clients'))
    main()


def test_failed_tenant_does_not_starve_another_dispatch_cycle(monkeypatch):
    from workers.dispatcher import run_batch
    monkeypatch.setenv('CLOUDSAVER_SCHEDULED_SCANS','false')
    tenants=SimpleNamespace(tenants=({'tenant_id':'broken'},{'tenant_id':'healthy'}))
    class Repo:
        def __init__(self):self.beats=[]
        def reconcile(self,tid):
            if tid=='broken':raise ConnectionError('private-database-url')
        def heartbeat(self,tid,success):self.beats.append((tid,success))
        def claim(self,tid,kinds):return None
    repository=Repo()
    with httpx.Client() as client:
        assert run_batch(tenants,repository,targets=(),publish_scan=lambda *_:None,client=client,jobs=None)==0
    assert repository.beats==[('broken',False),('healthy',True)]


def test_target_configuration_is_tenant_bound_and_does_not_reveal_secrets(monkeypatch):
    config=[{'target_id':'finops','tenant_id':TENANT,'channel':'slack','url_env':'CLOUDSAVER_WEBHOOK_FINOPS'}]
    monkeypatch.setenv('CLOUDSAVER_NOTIFICATION_TARGETS',json.dumps(config))
    monkeypatch.setenv('CLOUDSAVER_WEBHOOK_FINOPS',TARGET.url)
    result=load_targets()
    assert result[0]==TARGET and result[0].public()=={'target_id':'finops','channel':'slack'}
    assert 'test-secret' not in repr(result)
    monkeypatch.setenv('CLOUDSAVER_WEBHOOK_FINOPS','https://127.0.0.1/private-secret')
    with pytest.raises(ValueError,match='configuration is invalid') as error:
        load_targets()
    assert 'private-secret' not in str(error.value)


@pytest.mark.parametrize('changes',[{'tenant_id':'invalid'},{'url_env':'AWS_SECRET_ACCESS_KEY'},{'channel':'arbitrary'},
                                  {'target_id':'../other'},{'url':'https://example.com'}])
def test_target_config_rejects_untrusted_fields(monkeypatch,changes):
    row={'target_id':'finops','tenant_id':TENANT,'channel':'slack','url_env':'CLOUDSAVER_WEBHOOK_FINOPS',**changes}
    monkeypatch.setenv('CLOUDSAVER_NOTIFICATION_TARGETS',json.dumps([row]))
    monkeypatch.setenv('CLOUDSAVER_WEBHOOK_FINOPS',TARGET.url)
    with pytest.raises(ValueError):
        load_targets()


def test_identity_metadata_does_not_resolve_webhook_secrets(monkeypatch):
    from app.operations import workspace_operations
    row={'target_id':'finops','tenant_id':TENANT,'channel':'slack','url_env':'CLOUDSAVER_WEBHOOK_FINOPS'}
    monkeypatch.setenv('CLOUDSAVER_NOTIFICATION_TARGETS',json.dumps([row]))
    monkeypatch.delenv('CLOUDSAVER_WEBHOOK_FINOPS',raising=False)
    assert workspace_operations({'tenant_id': TENANT})['notification_webhook_configured'] is True
    assert workspace_operations({'tenant_id': '22222222-2222-4222-8222-222222222222'})['notification_webhook_configured'] is False
    with pytest.raises(ValueError):
        load_targets()
