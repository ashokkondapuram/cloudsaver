"""Durable polling worker: one scope at a time, bounded concurrency, no broker-dependent publication gap."""
import logging,signal,threading
from datetime import datetime,timezone
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.billing_jobs import BillingJobs


def run_once(settings,leader_probe=None):
    from app.config import require_directory_freshness
    require_directory_freshness(settings)
    jobs=BillingJobs(EnterpriseStore(settings));count=0
    def fresh_workspace(tenant):
        require_directory_freshness(settings)
        return settings.registry.get(tenant['tenant_id']) if settings.registry else tenant
    for tenant in settings.tenants:
        if leader_probe:leader_probe()
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
        while not stop.is_set():
            if lock:lock.execute('SELECT 1')  # fail-stop on leader connection loss
            try:run_once(settings,lambda:lock.execute('SELECT 1') if lock else None)
            except Exception:logging.getLogger('cloudsaver.billing').warning('Billing worker iteration unavailable')
            stop.wait(5)

if __name__=='__main__':main()
