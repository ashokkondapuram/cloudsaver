"""Opt-in Celery ingestion. Import creates configuration, never cloud/DB clients."""
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

from celery import Celery
from celery.signals import worker_shutdown

from app.config import Settings
from app.schemas import ScanSummary


def enabled(name):
    return os.getenv(name, '').lower() == 'true'


broker = os.getenv('REDIS_URL', 'redis://redis:6379/1')
celery_app = Celery('cloudsaver_scanner', broker=broker, backend=broker)
celery_app.conf.update(task_serializer='json', accept_content=['json'], result_serializer='json',
                       timezone='UTC', enable_utc=True, task_acks_late=True,
                       task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
                       task_time_limit=600, task_soft_time_limit=570,
                       broker_connection_timeout=5,
                       broker_transport_options={'visibility_timeout': 900,'socket_timeout':5,'socket_connect_timeout':5,'retry_on_timeout':False},
                       result_expires=86400)
if enabled('CLOUDSAVER_SCHEDULED_SCANS'):
    interval = int(os.getenv('CLOUDSAVER_SCAN_INTERVAL_SECONDS', '3600'))
    if interval < 300:
        raise ValueError('Scheduled scan interval must be at least 300 seconds')
    celery_app.conf.beat_schedule = {'scan-authorized-subscriptions': {
        'task': 'workers.tasks.scheduled_scan_all', 'schedule': float(interval)}}


class JobBusy(RuntimeError):
    pass


class UnauthorizedJob(ValueError):
    pass


class TerminalJob(RuntimeError):
    pass


@worker_shutdown.connect
def close_worker_credentials(**kwargs):
    # Resolve this lazily: importing tasks must not create credential clients.
    from app.keyvault import close_providers
    close_providers()
    from database.connection import dispose
    dispose()


class RedisLease:
    """A lease outlives the task's hard time limit; release verifies ownership."""
    RELEASE = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
    RENEW = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],ARGV[2]) else return 0 end"

    def __init__(self, url, *, client=None, ttl=660):
        import redis
        if not 1 <= ttl <= 3600:
            raise ValueError('Invalid lease TTL')
        self.ttl = ttl
        self.client = client or redis.Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)

    def acquire(self, tenant_id, token):
        return bool(self.client.set('cloudsaver:scan-lease:' + tenant_id, token, nx=True, ex=self.ttl))

    def renew(self, tenant_id, token):
        return bool(self.client.eval(self.RENEW, 1, 'cloudsaver:scan-lease:' + tenant_id, token, self.ttl))

    def release(self, tenant_id, token):
        self.client.eval(self.RELEASE, 1, 'cloudsaver:scan-lease:' + tenant_id, token)

    def close(self):
        self.client.close()


def authorized_tenant(settings, repository, tenant_id, requested):
    tenant_id = str(UUID(tenant_id))
    tenant = next((t for t in settings.tenants if t['tenant_id'] == tenant_id), None)
    if tenant is None:
        raise UnauthorizedJob('Worker tenant is not configured')
    if not isinstance(requested, list) or not 1 <= len(requested) <= 100:
        raise UnauthorizedJob('Invalid subscription selection')
    requested = [str(UUID(s)) for s in requested]
    if len(set(requested)) != len(requested):
        raise UnauthorizedJob('Duplicate subscription selection')
    allowed = set(tenant['subscription_ids']) & set(repository.active_subscriptions(tenant_id))
    if not set(requested) <= allowed:
        raise UnauthorizedJob('Worker subscription scope is not currently authorized')
    return dict(tenant, subscription_ids=requested)


def run_scan_job(settings, tenant_id, subscriptions, job_id, repository, lease, *,
                 scanner=None, notification_targets=(), final_attempt=False):
    """Dependency-injected core used by Celery and behavior-based unit tests."""
    from app.scanner import scan_live
    from app.pricing import attribute_finding_cost
    job_id = str(UUID(job_id))
    tenant = authorized_tenant(settings, repository, tenant_id, subscriptions)
    tenant_id = tenant['tenant_id']
    from app.entitlements import get_tier_entitlements, enforce_subscription_quota
    tier = repository.plan_tier(tenant_id)
    entitlements = get_tier_entitlements(tier)
    origin = repository.job_origin(tenant_id, job_id) if hasattr(repository, 'job_origin') else 'scheduled'
    if origin != 'interactive' and entitlements.allowed_scan_frequencies == ['manual']:
        raise UnauthorizedJob('This workspace does not permit scheduled scans')
    enforce_subscription_quota(tier, len(subscriptions), adding_count=0)
    if settings.mode == 'azure' and os.getenv('CLOUDSAVER_CREDENTIAL_PROVIDER', 'env') == 'keyvault' and not entitlements.can_use_keyvault:
        raise UnauthorizedJob('Workspace plan does not permit Key Vault credentials')
    repository.queue_job(tenant_id, job_id)
    existing = repository.get_job(tenant_id, job_id)
    if existing and existing['status'] == 'completed':
        return dict(job_id=job_id, status='completed', scan_id=existing['scan_id'])
    if existing and existing['status'] == 'failed':
        raise TerminalJob('Job already failed permanently')
    token = str(uuid4())
    if not lease.acquire(tenant_id, token):
        raise JobBusy('Workspace scan is already running')
    from workers.lease import LeaseHeartbeat
    heartbeat = LeaseHeartbeat(lease, tenant_id, token)
    heartbeat.start()
    try:
        if not repository.start_job(tenant_id, job_id, token):
            completed = repository.get_job(tenant_id, job_id)
            if completed and completed['status'] == 'completed':
                return dict(job_id=job_id, status='completed', scan_id=completed['scan_id'])
            raise TerminalJob('Job exhausted its durable attempt limit')
        findings = scanner(tenant) if scanner else scan_live(tenant)
        if len(findings) > entitlements.max_resources_per_scan:
            raise UnauthorizedJob('Scan exceeds workspace resource quota')
        enriched = []
        for finding in findings:
            enriched.append(attribute_finding_cost(finding) if finding.get('cloud_provider', 'azure') == 'azure' else finding)
        findings = enriched
        for finding in findings:
            sub = str(UUID(finding['subscription_id']))
            if sub not in tenant['subscription_ids'] or not finding['resource_id'].lower().startswith(f'/subscriptions/{sub}/'):
                raise UnauthorizedJob('Scanner returned an unauthorized resource')
        known = all(f.get('estimated_monthly_waste_usd') is not None for f in findings)
        from app.multi_cloud import scope_fingerprint
        scan = ScanSummary.model_validate(dict(
            scan_id=str(uuid5(UUID(job_id), 'scan')), timestamp=datetime.now(timezone.utc).isoformat(),
            mode=settings.mode, status='completed', subscriptions_scanned=len(subscriptions),
            total_items_found=len(findings), findings=findings,
            cloud_providers=['azure'],
            scope_fingerprint=scope_fingerprint(tenant, ['azure']),
            total_monthly_waste_usd=round(sum(f['estimated_monthly_waste_usd'] for f in findings), 2) if known and findings else None,
        )).model_dump()
        heartbeat.ensure_owned()
        repository.complete_job(tenant_id, job_id, scan, tenant['subscription_ids'], token=token, notification_targets=notification_targets)
    except TerminalJob:
        raise
    except Exception:
        repository.fail_job(tenant_id, job_id, 'scan_failed', final_attempt, token=token)
        raise
    finally:
        heartbeat.stop()
        # Lease expiry remains a safe fallback if Redis is unavailable on release.
        try:
            lease.release(tenant_id, token)
        except Exception:
            pass
    return dict(job_id=job_id, status='completed', scan_id=scan['scan_id'])


def dependencies():
    from workers.storage import JobRepository
    settings = Settings.load()
    return settings, JobRepository(settings.database_url), RedisLease(broker)


@celery_app.task(name='workers.tasks.execute_subscription_scan', bind=True, max_retries=3)
def execute_subscription_scan(self, tenant_id, subscription_ids):
    import psycopg
    import redis
    import httpx
    from billiard.exceptions import SoftTimeLimitExceeded
    from app.scanner import ScanError
    from azure.core.exceptions import AzureError
    from app.keyvault import CredentialError
    job_id = str(UUID(self.request.id))
    repository = None
    lease = None
    verified = False
    try:
        settings, repository, lease = dependencies()
        if not repository.verify_delivery(tenant_id,job_id,subscription_ids):
            raise UnauthorizedJob('Task does not match durable delivery intent')
        verified = True
        from app.delivery_config import load_targets
        targets = tuple(t for t in load_targets() if t.tenant_id == tenant_id) if enabled('CLOUDSAVER_AUTOMATED_ALERTS') else ()
        return run_scan_job(settings, tenant_id, subscription_ids, job_id, repository, lease,
                            notification_targets=targets,
                            final_attempt=self.request.retries >= self.max_retries)
    except TerminalJob:
        raise RuntimeError('Scheduled scan job is terminal') from None
    except (UnauthorizedJob, ValueError):
        # Untrusted or revoked scopes are permanent failures, never widened or retried.
        configured = {t['tenant_id'] for t in settings.tenants} if repository else set()
        if repository and verified and tenant_id in configured:
            repository.fail_job(tenant_id, job_id, 'unauthorized_scope', True)
        raise RuntimeError('Worker subscription authorization failed') from None
    except (JobBusy, ScanError, AzureError, CredentialError, psycopg.Error, redis.RedisError, httpx.HTTPError,
            SoftTimeLimitExceeded, TimeoutError, ConnectionError) as exc:
        if repository:
            try:
                repository.fail_job(tenant_id, job_id, 'scan_failed', self.request.retries >= self.max_retries)
            except Exception:
                pass
        if self.request.retries >= self.max_retries:
            raise RuntimeError('Scheduled scan exhausted bounded retries') from None
        delay = 300 if isinstance(exc, JobBusy) else min(60 * 2 ** self.request.retries, 300)
        raise self.retry(exc=RuntimeError('Scheduled scan failed'), countdown=delay) from None
    except Exception:
        if repository:
            try:
                repository.fail_job(tenant_id, job_id, 'unexpected_failure', True)
            except Exception:
                pass
        raise RuntimeError('Scheduled scan failed permanently') from None
    finally:
        if lease:
            try:
                lease.close()
            except Exception:
                pass


@celery_app.task(name='workers.tasks.scheduled_scan_all')
def scheduled_scan_all():
    if not enabled('CLOUDSAVER_SCHEDULED_SCANS'):
        return {'scheduled': 0, 'enabled': False}
    settings, repository, lease = dependencies()
    lease.close()
    count = 0
    for tenant in settings.tenants:
        active = sorted(set(repository.active_subscriptions(tenant['tenant_id'])) & set(tenant['subscription_ids']))
        if not active:
            continue
        tier = repository.plan_tier(tenant['tenant_id'])
        if tier == 'STARTER':
            continue
        minimum = 86400 if tier == 'GROWTH' else 3600
        job_id = str(uuid4())
        if not repository.reserve_scheduled_job(tenant['tenant_id'], job_id, minimum, active):
            continue
        # Dispatcher publishes this committed outbox intent; no broker I/O here.
        count += 1
    return {'scheduled': count, 'enabled': True}
