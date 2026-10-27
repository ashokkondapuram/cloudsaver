"""Durable polling worker: one scope at a time, bounded concurrency, no broker-dependent publication gap."""
import logging,os,signal,threading
from datetime import datetime,timedelta,timezone
from uuid import NAMESPACE_URL,uuid5
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.billing_jobs import BillingJobs


def _auto_submit(jobs,tenant,now):
    """Keep cost data fresh on its own schedule, independent of any scan. One attempt per interval per tenant, deduplicated by day bucket."""
    from app.collectors.billing_sync import bindings
    from app.focus import FocusError
    from app.v150_store import WorkflowConflict
    try:
        if not bindings(tenant):return
    except FocusError:return
    tid=tenant['tenant_id']
    interval=timedelta(hours=float(os.getenv('CLOUDSAVER_BILLING_SYNC_INTERVAL_HOURS','24')))
    with jobs.store.transaction(tid) as db:
        active=db.execute("SELECT 1 FROM billing_sync_jobs WHERE tenant_id=%s AND state IN ('queued','running','cancel_requested') LIMIT 1",(tid,)).fetchone()
        if active:return
        last=db.execute("SELECT updated_at FROM billing_sync_jobs WHERE tenant_id=%s AND state='completed' ORDER BY updated_at DESC LIMIT 1",(tid,)).fetchone()
    if last and datetime.fromisoformat(str(last[0]).replace('Z','+00:00'))>now-interval:return
    key=str(uuid5(NAMESPACE_URL,f'billing-auto:{tid}:{now.strftime("%Y-%m-%d-%H")}'))
    try:jobs.submit(tenant,key)
    except WorkflowConflict:pass


def _recover_orphaned_jobs(settings):
    """Only one leader process holds the advisory lock below, so any job still marked 'running' at
    startup belongs to a previous process that is gone (crash, deploy, restart) -- its in-memory
    progress is lost and its long lease would otherwise strand it for hours. Requeue it immediately."""
    jobs=BillingJobs(EnterpriseStore(settings));now=datetime.now(timezone.utc).isoformat()
    for tenant in settings.tenants:
        with jobs.store.transaction(tenant['tenant_id'],write=True) as db:
            db.execute("UPDATE billing_sync_jobs SET state='queued',lease_token=NULL,lease_until=NULL,updated_at=%s "
                       "WHERE tenant_id=%s AND state IN ('running','cancel_requested')",(now,tenant['tenant_id']))


def run_once(settings,leader_probe=None):
    from app.config import require_directory_freshness
    require_directory_freshness(settings)
    jobs=BillingJobs(EnterpriseStore(settings));count=0;now=datetime.now(timezone.utc)
    def fresh_workspace(tenant):
        require_directory_freshness(settings)
        return settings.registry.get(tenant['tenant_id']) if settings.registry else tenant
    for tenant in settings.tenants:
        if leader_probe:leader_probe()
        _auto_submit(jobs,tenant,now)
        claim=jobs.claim(tenant['tenant_id'])
        if claim:
            jobs.execute_scope(tenant,claim,refresh=lambda:fresh_workspace(tenant));count+=1
    return count


def main():
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    settings=Settings.load()
    # One elected polling worker across replicas. A separate session lock is
    # released by PostgreSQL on process loss; scope commit fencing is independent.
    from contextlib import nullcontext
    import psycopg
    with psycopg.connect(settings.database_url,connect_timeout=5,autocommit=True) if settings.database_url else nullcontext(None) as lock:
        if lock:
            if not lock.execute("SELECT pg_try_advisory_lock(hashtextextended('cloudsaver:billing-worker',0))").fetchone()[0]:return
        try:_recover_orphaned_jobs(settings)
        except Exception:logging.getLogger('cloudsaver.billing').warning('Orphaned billing job recovery unavailable')
        while not stop.is_set():
            if lock:lock.execute('SELECT 1')  # fail-stop on leader connection loss
            try:run_once(settings,lambda:lock.execute('SELECT 1') if lock else None)
            except Exception:logging.getLogger('cloudsaver.billing').warning('Billing worker iteration unavailable')
            stop.wait(5)

if __name__=='__main__':main()
