"""Opt-in PostgreSQL delivery dispatcher. Run as a separate supervised process."""
import logging
import os
import random
import signal
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.delivery_config import enabled, load_targets

logger=logging.getLogger('cloudsaver.delivery')


def retry_after(value):
    try:
        seconds=float(value)
    except (ValueError,TypeError):
        try:
            parsed=parsedate_to_datetime(value)
            if not parsed.tzinfo:
                return 60
            seconds=(parsed-datetime.now(timezone.utc)).total_seconds()
        except (ValueError,TypeError,OverflowError):
            return 60
    import math
    return min(3600,max(1,seconds)) if math.isfinite(seconds) else 60


def notification_message(event,target):
    text=f"CloudSaver scan completed: {event['payload']['findings_count']} review findings across {event['payload']['scopes_count']} scopes."
    # Slack and Teams workflow webhooks use different envelope formats.
    if target.channel=='slack':
        return {'text':text,'blocks':[{'type':'section','text':{'type':'plain_text','text':text}}]}
    return {'type':'message','attachments':[{'contentType':'application/vnd.microsoft.card.adaptive','contentUrl':None,
        'content':{'$schema':'http://adaptivecards.io/schemas/adaptive-card.json','type':'AdaptiveCard','version':'1.4',
                   'body':[{'type':'TextBlock','text':text,'wrap':True}]}}]}


def dispatch_one(repository,tenant_id,*,targets,publish_scan,client,kinds=('scan','notification'),authorize_scan=None,authorize_job=None):
    event=repository.claim(tenant_id,kinds)
    if not event:
        return False
    outcome,error,delay='retry','transport_unavailable',min(30*2**(event['attempts']-1),1800)+random.uniform(0,10)
    try:
        if event['kind']=='scan':
            from app.scan_selection import from_payload
            selection=from_payload(event['payload'])
            if ((authorize_scan and not authorize_scan(tenant_id,selection))
                    or (authorize_job and not authorize_job(event))):
                outcome,error='dead_letter','scope_revoked'
            else:
                publish_scan(tenant_id,selection,event['job_id'])
                outcome,error='published',None
        else:
            target=next((t for t in targets if t.tenant_id==tenant_id and t.target_id==event['target_id']),None)
            if not target or target.fingerprint!=event['target_fingerprint']:
                outcome,error='dead_letter','target_changed'
            else:
                # Stream and close without reading a provider-controlled response body.
                # No workspace Authorization header, URL, payload or provider body is logged.
                with client.stream('POST',target.url,json=notification_message(event,target),
                                   headers={'X-CloudSaver-Event-ID':event['id']},follow_redirects=False) as response:
                    if 200<=response.status_code<300:
                        outcome,error='delivered',None
                    elif response.status_code==429:
                        error,delay='rate_limited',retry_after(response.headers.get('retry-after'))
                    elif response.status_code>=500 or response.status_code==408:
                        error='provider_unavailable'
                    else:
                        outcome,error='dead_letter','provider_rejected'
    except (httpx.HTTPError,TimeoutError,ConnectionError,OSError):
        pass
    except Exception:
        # Broker libraries wrap transport errors in several exception types.
        # Persist a bounded retry without retaining exception text/credentials.
        pass
    repository.finish(tenant_id,event,outcome=outcome,error_code=error,retry_after=delay)
    return True


def run_batch(settings,repository,*,targets,publish_scan,client,jobs,limit=5,should_stop=lambda:False):
    from app.operations import platform_flags
    scheduled=platform_flags(settings)[0]
    kinds=[]
    if scheduled or os.getenv('CLOUDSAVER_INTERACTIVE_JOBS','false').lower()=='true':
        kinds.append('scan')
    # Explicit manual delivery does not require the automated-alerts switch.
    kinds.append('notification')
    processed=0
    for tenant in settings.tenants:
        if should_stop():
            break
        tenant_id=tenant['tenant_id']
        try:
            repository.reconcile(tenant_id)
            def authorize(tid,subscriptions):
                from workers.tasks import authorized_tenant
                try:
                    authorized_tenant(settings,jobs,tid,subscriptions)
                    return True
                except ValueError:
                    return False
            for _ in range(limit):
                if should_stop():
                    break
                def authorize_job(event):
                    origin = event['payload'].get('origin', 'scheduled')
                    if origin == 'interactive':
                        return os.getenv('CLOUDSAVER_INTERACTIVE_JOBS','false').lower() == 'true'
                    from workers.tasks import workspace_entitlements
                    return scheduled and set(workspace_entitlements(tenant,jobs).allowed_scan_frequencies)>{'manual'}
                if not dispatch_one(repository,tenant_id,targets=targets,publish_scan=publish_scan,client=client,kinds=kinds,authorize_scan=authorize,authorize_job=authorize_job):
                    break
                processed+=1
            repository.heartbeat(tenant_id,True)
        except Exception:
            # One tenant's database/authorization failure must not starve others.
            logger.error('Tenant delivery cycle failed; durable work retained')
            try:
                repository.heartbeat(tenant_id,False)
            except Exception:
                pass
    return processed


def main():
    # Disabled process exits before any DB, broker or HTTP client is created.
    if not enabled():
        logger.warning('Durable delivery is disabled by operator configuration')
        return
    from app.config import Settings
    from database.delivery import DeliveryRepository
    from workers.storage import JobRepository
    from workers.tasks import execute_subscription_scan
    settings=Settings.load()
    from workers.health import WorkerHealth
    health=WorkerHealth().start()
    configured={t['tenant_id'] for t in settings.tenants}
    if any(t.tenant_id not in configured for t in load_targets()):
        raise ValueError('Notification targets must belong to configured tenants')
    repository=DeliveryRepository(settings.database_url)
    jobs=JobRepository(settings.database_url)
    stop=threading.Event()
    for name in (signal.SIGTERM,signal.SIGINT):
        signal.signal(name,lambda *_:stop.set())
    def publish(tid,subscriptions,job_id):
        execute_subscription_scan.apply_async(args=[tid,subscriptions],task_id=job_id,retry=False)
    with httpx.Client(timeout=httpx.Timeout(15,connect=5),follow_redirects=False) as client:
        while not stop.is_set():
            try:
                count=run_batch(settings,repository,targets=load_targets(settings),publish_scan=publish,client=client,jobs=jobs,should_stop=stop.is_set)
                health.touch()
            except Exception:
                health.touch(False)
                # Avoid logging a DSN, broker URL or provider exception.
                logger.error('Delivery batch failed; durable work retained')
                count=0
            stop.wait(1 if count else 5)
    health.close()


if __name__=='__main__':
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    main()
