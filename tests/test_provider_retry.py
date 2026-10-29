from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from uuid import uuid4
import httpx
import pytest

from app.provider_retry import LocalBudget, ProviderDeferred, ProviderReadError, read_json, retry_after


class Clock:
    def __init__(self):self.now=0;self.sleeps=[]
    def __call__(self):return self.now
    def sleep(self,seconds):self.sleeps.append(seconds);self.now+=seconds


def test_retry_after_dates_milliseconds_invalid_values_and_minimum_delay():
    now=datetime.now(timezone.utc).replace(microsecond=0)
    assert retry_after({'retry-after':format_datetime(now+timedelta(seconds=75))},now=now)==75
    assert retry_after({'retry-after':'30','x-ms-retry-after-ms':'61000'})==61
    for value in ('NaN','inf','-5','invalid'):
        assert retry_after({'retry-after':value}) is None
    with pytest.raises(ProviderReadError):retry_after({'retry-after':'999999999'})


def test_shared_cooldown_retries_read_and_never_exposes_failure_body():
    clock=Clock();budget=LocalBudget(clock);calls=[]
    def provider(request):
        calls.append(request)
        return httpx.Response(429,headers={'retry-after':'2'},text='secret provider content') if len(calls)==1 else httpx.Response(200,json={'value':[]})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert read_json(client,'GET','https://provider.example',quota_key='scope',budget=budget,clock=clock,sleep=clock.sleep,jitter=lambda *_:.5)=={'value':[]}
    assert clock.sleeps==[2] and len(calls)==2
    budget.defer('scope',90)
    assert budget.acquire('scope',0)==90 and budget.acquire('other-scope',0)==0


def test_long_wait_defers_without_sleeping_or_shortening_retry_after():
    clock=Clock();budget=LocalBudget(clock);calls=[]
    def provider(request):calls.append(request);return httpx.Response(429,headers={'retry-after':'120'})
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        for _ in range(2):
            with pytest.raises(ProviderDeferred) as exc:
                read_json(client,'GET','https://provider.example',quota_key='scope',budget=budget,clock=clock,sleep=clock.sleep)
            assert exc.value.retry_after==120
    assert len(calls)==1 and clock.sleeps==[]


@pytest.mark.parametrize('status',[301,401,403,404])
def test_permanent_failures_and_mutations_are_not_retried(status):
    calls=[]
    def provider(request):calls.append(request);return httpx.Response(status)
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ProviderReadError):read_json(client,'GET','https://example.test',quota_key='x',budget=LocalBudget())
        with pytest.raises(ValueError):read_json(client,'POST','https://example.test',quota_key='x')
    assert len(calls)==1


def test_response_bounds_and_invalid_json():
    for content in (b'[]',b'{bad',b'x'*21):
        with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=content))) as client:
            with pytest.raises(ProviderReadError):read_json(client,'GET','https://example.test',quota_key='x',budget=LocalBudget(),max_bytes=20)


def test_production_cannot_fall_back_to_process_local_coordination(monkeypatch):
    from app.provider_retry import shared_budget
    monkeypatch.delenv('REDIS_URL',raising=False);monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT','production')
    with pytest.raises(ProviderReadError):shared_budget()


def test_bigquery_billing_transport_does_not_require_azure_subscription(monkeypatch):
    from app.collectors import billing_sync
    calls=[]
    def provider(request):calls.append(request);return httpx.Response(200,json={'jobComplete':True,'rows':[]})
    factory=httpx.Client
    monkeypatch.setattr(billing_sync.httpx,'Client',lambda **kw:factory(transport=httpx.MockTransport(provider),**kw))
    monkeypatch.delenv('REDIS_URL',raising=False)
    result=billing_sync._post('https://bigquery.googleapis.com/bigquery/v2/projects/billing-project/queries','test-token',{'query':'SELECT 1'})
    assert result['jobComplete'] and len(calls)==1


def test_local_pacing_is_atomic_across_competing_callers():
    from concurrent.futures import ThreadPoolExecutor
    clock=Clock();budget=LocalBudget(clock)
    with ThreadPoolExecutor(max_workers=8) as pool:waits=list(pool.map(lambda _:budget.acquire('scope',15),range(8)))
    assert waits.count(0)==1 and waits.count(15)==7


def test_real_redis_coordinates_independent_workers():
    import os
    from concurrent.futures import ThreadPoolExecutor
    from app.provider_retry import RedisBudget
    url=os.getenv('CLOUDSAVER_TEST_REDIS_URL')
    if not url:pytest.skip('Requires disposable Redis')
    left,right=RedisBudget(url),RedisBudget(url);key='test:'+str(uuid4())
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            waits=list(pool.map(lambda i:(left if i%2 else right).acquire(key,15),range(8)))
        assert waits.count(0)==1 and all(0<=w<=15 for w in waits)
        left.defer(key,90)
        assert 89<=right.acquire(key,0)<=90
    finally:
        import hashlib
        left.client.delete('cloudsaver:provider-budget:'+hashlib.sha256(key.encode()).hexdigest())
        left.client.close();right.client.close()
