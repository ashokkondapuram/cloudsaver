"""Opt-in Celery ingestion. Import creates configuration, never cloud/DB clients."""
import os
import logging
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
# The beat only ticks; platform and tenant settings decide on each tick who is due.
tick = int(os.getenv('CLOUDSAVER_SCHEDULER_TICK_SECONDS', '300'))
if not 60 <= tick <= 3600:
    raise ValueError('Scheduler tick must be between 60 and 3600 seconds')
celery_app.conf.beat_schedule = {'scan-authorized-subscriptions': {
    'task': 'workers.tasks.scheduled_scan_all', 'schedule': float(tick)}}
if os.getenv('CLOUDSAVER_AUTO_BILLING_SYNC','true').lower()=='true':
    celery_app.conf.beat_schedule['sync-authorized-cloud-billing']={
        'task':'workers.tasks.sync_authorized_cloud_billing','schedule':3600.0,'options':{'expires':3600}}
ai_tick = int(os.getenv('CLOUDSAVER_AI_BATCH_TICK_SECONDS', '30'))
if not 10 <= ai_tick <= 3600:
    raise ValueError('AI batch tick must be between 10 and 3600 seconds')
if enabled('CLOUDSAVER_AI_ENABLED'):
    celery_app.conf.beat_schedule['process-ai-batches'] = {
        'task': 'workers.tasks.process_ai_batches', 'schedule': float(ai_tick), 'options': {'expires': ai_tick}}


class JobBusy(RuntimeError):
    pass


@celery_app.task(name='workers.tasks.sync_authorized_cloud_billing')
def sync_authorized_cloud_billing():
    from app.collectors.billing_sync import bindings
    from app.billing_jobs import BillingJobs
    from app.enterprise_store import EnterpriseStore
    from app.focus import FocusRepository
    settings=Settings.load()
    result=[]
    for tenant in settings.tenants:
        if (tenant.get('plan') or {}).get('access_suspended') is True:continue
        try:
            if bindings(tenant):
                run=BillingJobs(EnterpriseStore(settings)).submit(tenant,'schedule:'+datetime.now(timezone.utc).strftime('%Y-%m-%dT%H'),currency=None)
                result.append(dict(tenant_id=tenant['tenant_id'],status=run['status'],run_id=run['id']))
        except Exception:
            result.append(dict(tenant_id=tenant['tenant_id'],status='unavailable'))
    return result


class UnauthorizedJob(ValueError):
    pass


class TerminalJob(RuntimeError):
    pass


@worker_shutdown.connect
def close_worker_credentials(**kwargs):
    # Resolve this lazily: importing tasks must not create credential clients.
    from app.cloud_identity import close_providers
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
    from app.scan_selection import normalize,restrict,azure_ids
    try:
        requested=normalize(requested)
        result=restrict(tenant,requested)
    except (ValueError,TypeError,KeyError):
        raise UnauthorizedJob('Worker scope selection is invalid or revoked') from None
    if not set(azure_ids(requested))<=set(repository.active_subscriptions(tenant_id)):
        raise UnauthorizedJob('Worker Azure subscription is not currently connected')
    return result


def workspace_entitlements(tenant, repository):
    """Projected platform entitlements; organizations.plan_tier only feeds the TIER_LIMITS fallback."""
    from app.entitlements import entitlements_for
    if tenant.get('plan'):
        return entitlements_for(tenant)
    return entitlements_for(dict(tenant, plan_tier=repository.plan_tier(tenant['tenant_id'])))


def run_scan_job(settings, tenant_id, subscriptions, job_id, repository, lease, *,
                 scanner=None, notification_targets=(), final_attempt=False):
    """Dependency-injected core used by Celery and behavior-based unit tests."""
    from app.scanner import scan_live
    from app.pricing import attribute_finding_cost
    job_id = str(UUID(job_id))
    tenant = authorized_tenant(settings, repository, tenant_id, subscriptions)
    tenant_id = tenant['tenant_id']
    from app.entitlements import enforce_subscription_quota,enforce_providers
    from app.scan_selection import count,providers,azure_ids
    entitlements = workspace_entitlements(tenant, repository)
    origin = repository.job_origin(tenant_id, job_id) if hasattr(repository, 'job_origin') else 'scheduled'
    if origin != 'interactive' and entitlements.allowed_scan_frequencies == ['manual']:
        raise UnauthorizedJob('This workspace does not permit scheduled scans')
    enforce_subscription_quota(entitlements, count(subscriptions), adding_count=0)
    selected_providers=providers(subscriptions)
    enforce_providers(entitlements,selected_providers)
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
        from app.effective_rules import policy_for_tenant
        from app.config import key_verifier
        policy = policy_for_tenant(tenant_id)
        rule_ids = set(policy['enabled_rule_ids']) if policy is not None else None
        if key_verifier() == 'identity' and policy is None:
            from app.scanner import ScanError
            raise ScanError('Analysis policy is unavailable; no scan was saved.')
        inventory = []
        if scanner:
            scanned = scanner(tenant)
            if isinstance(scanned, tuple):
                findings, inventory = scanned
            else:
                findings = scanned
        else:
            if isinstance(subscriptions,dict):
                from app.multi_cloud import scan_multi_cloud
                findings,inventory=scan_multi_cloud(tenant,selected_providers,enabled_rule_ids=rule_ids)
            else:
                findings, inventory = scan_live(tenant, enabled_rule_ids=rule_ids)
        resource_count = len(inventory) if inventory else len(findings)
        if resource_count > entitlements.max_resources_per_scan:
            raise UnauthorizedJob('Scan exceeds workspace resource quota')
        enriched = []
        for finding in findings:
            enriched.append(attribute_finding_cost(finding))
        findings = enriched
        from app.cloud_scope import validate_finding_scope
        try:
            for finding in findings:validate_finding_scope(finding,tenant)
        except (ValueError,KeyError):
            raise UnauthorizedJob('Scanner returned an unauthorized resource') from None
        for observation in inventory:
            validate_finding_scope(dict(observation,rule_id=observation.get('inventory_rule_id','INVENTORY')),tenant)
        from app.multi_cloud import scope_fingerprint
        from app.analysis_rules import evaluate_inventory, RULES, VERSION
        from app.inventory import coverage, coverage_manifest
        from app.dependencies import canonical_inventory, group_opportunities
        from app.pricing import opportunity_totals
        observed_at = datetime.now(timezone.utc).isoformat()
        inventory = canonical_inventory(inventory, observed_at)
        from app.collectors.provenance import compact
        source_ledger = compact(inventory, findings, observed_at)
        from app.scan_scope_manifest import completed_scopes
        findings = group_opportunities(findings, inventory)
        policies = {item['id']: item for item in (policy or {}).get('items', [])}
        if rule_ids is not None:
            from app.kubernetes_rules import DEFINITIONS as KUBERNETES_RULES
            from app.resource_catalog import definitions
            for rid, *_ in (*RULES, *KUBERNETES_RULES, *definitions()):
                policies.setdefault(rid, {'enabled': rid in rule_ids})
        outcomes = evaluate_inventory(inventory, policies=policies, observed_at=observed_at)
        from app.multicloud_rules import materialize
        findings=group_opportunities(materialize(findings,inventory,outcomes),inventory)
        from app.cloud_scope import validate_finding_scope
        for finding in findings:validate_finding_scope(finding,tenant)
        opportunity = opportunity_totals(findings)
        scan = ScanSummary.model_validate(dict(
            scan_id=str(uuid5(UUID(job_id), 'scan')), timestamp=datetime.now(timezone.utc).isoformat(),
            mode=settings.mode, status='completed', subscriptions_scanned=len(azure_ids(subscriptions)),
            total_items_found=len(inventory) if inventory else len(findings), findings=findings, inventory=inventory,
            cloud_providers=selected_providers, source_ledger=source_ledger,
            scope_results=completed_scopes(tenant,selected_providers,source_ledger) if scanner is None else [],
            scope_fingerprint=scope_fingerprint(tenant, selected_providers),
            total_monthly_waste_usd=opportunity['total_monthly_opportunity_usd'],
            opportunity_summary=opportunity, rule_evaluations=outcomes,
            rule_manifest={'version': VERSION, 'policies': policies, 'workspace_version': (policy or {}).get('version'),
                           'enabled_rule_ids': sorted(rule_ids) if rule_ids is not None else None},
            coverage=coverage(inventory, findings, outcomes),
            coverage_manifest=coverage_manifest(inventory, findings, outcomes),
        )).model_dump()
        heartbeat.ensure_owned()
        repository.complete_job(tenant_id, job_id, scan, subscriptions, token=token, notification_targets=notification_targets)
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
    from app.cloud_identity import CredentialError
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
        from app.operations import alerts_enabled
        workspace = next((t for t in settings.tenants if t['tenant_id'] == tenant_id), None)
        targets = (tuple(t for t in load_targets(settings) if t.tenant_id == tenant_id)
                   if workspace and alerts_enabled(settings, workspace, workspace_entitlements(workspace, repository)) else ())
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
    from app.operations import platform_flags, scheduled_interval
    if os.getenv('CLOUDSAVER_TENANT_REGISTRY', 'env') != 'database' and not platform_flags()[0]:
        return {'scheduled': 0, 'enabled': False}
    settings, repository, lease = dependencies()
    lease.close()
    if not platform_flags(settings)[0]:
        return {'scheduled': 0, 'enabled': False}
    count = 0
    for tenant in settings.tenants:
        active = sorted(set(repository.active_subscriptions(tenant['tenant_id'])) & set(tenant['subscription_ids']))
        from app.scan_selection import select
        from app.cloud_scope import configured_providers
        authorized=dict(tenant,subscription_ids=active)
        selected=configured_providers(authorized)
        if not selected:continue
        selection=active if selected==['azure'] else select(authorized,selected)
        interval = scheduled_interval(settings, tenant, workspace_entitlements(tenant, repository))
        if not interval:
            continue
        job_id = str(uuid4())
        if not repository.reserve_scheduled_job(tenant['tenant_id'], job_id, interval, selection):
            continue
        # Dispatcher publishes this committed outbox intent; no broker I/O here.
        count += 1
    return {'scheduled': count, 'enabled': True}


@celery_app.task(name='workers.tasks.process_ai_batches')
def process_ai_batches():
    """One worker at a time works through queued resource AI batches within each workspace's hourly budget."""
    if not enabled('CLOUDSAVER_AI_ENABLED'):
        return {'processed': 0, 'enabled': False}
    import redis
    from app.ai_advisory import AIGateway
    from app.enterprise_store import EnterpriseStore
    from app.inference_ledger import InferenceLedger
    from app.resource_batches import process_batches
    from app.resource_store import ResourceStore
    from app.store import PostgresStore, Store
    client = redis.Redis.from_url(broker, socket_connect_timeout=5, socket_timeout=5)
    token = str(uuid4())
    try:
        if not client.set('cloudsaver:ai-batch-lock', token, nx=True, ex=540):
            return {'processed': 0, 'enabled': True, 'busy': True}
        settings = Settings.load()
        scans = PostgresStore(settings.database_url) if settings.database_url else Store(settings.database)
        evidence = EnterpriseStore(settings)
        gateway = AIGateway(budget=InferenceLedger(evidence), settings=settings)
        processed = process_batches(settings.tenants, scans, ResourceStore(evidence), gateway,
                                    max_items=int(os.getenv('CLOUDSAVER_AI_BATCH_ITEMS_PER_TICK', '10')))
        return {'processed': processed, 'enabled': True}
    finally:
        try:
            client.eval(RedisLease.RELEASE, 1, 'cloudsaver:ai-batch-lock', token)
            client.close()
        except Exception:
            pass
