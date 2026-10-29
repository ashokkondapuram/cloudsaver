"""Elected polling worker: queues due observability connectors and collects one connector at a time."""
import logging,os,signal,threading
from uuid import uuid4
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.observability_store import ObservabilityStore
from app.v150_store import WorkflowConflict


def run_once(settings,leader_probe=None,*,collect=None):
    from app.config import require_directory_freshness
    require_directory_freshness(settings)
    repo=ObservabilityStore(EnterpriseStore(settings));count=0
    if os.getenv('CLOUDSAVER_OBSERVABILITY_SYNC','true')!='true':return 0
    def fresh_workspace(tenant):
        require_directory_freshness(settings)
        from app.keycloak import current_licence
        current=settings.registry.get(tenant['tenant_id']) if settings.registry else tenant
        return current_licence(current) if current else None
    for tenant in settings.tenants:
        if leader_probe:leader_probe()
        try:tenant=fresh_workspace(tenant)
        except Exception:
            logging.getLogger('cloudsaver.observability').warning('Workspace collection authorization unavailable')
            continue
        if not tenant:continue
        if not tenant.get('active',True) or (tenant.get('plan') or {}).get('access_suspended'):continue
        due=repo.due(tenant['tenant_id'])
        if due:
            try:repo.submit(tenant,'schedule:'+str(uuid4()),trigger='schedule',connector_ids=due)
            except WorkflowConflict:pass
        claim=repo.claim(tenant['tenant_id'])
        if claim:
            repo.execute(tenant,claim,collect=collect,refresh=lambda:fresh_workspace(tenant));count+=1
    return count


def main():
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    settings=Settings.load()
    from workers.health import WorkerHealth
    health=WorkerHealth().start()
    from contextlib import nullcontext
    import psycopg
    with psycopg.connect(settings.database_url,connect_timeout=5,autocommit=True) if settings.database_url else nullcontext(None) as lock:
        if lock:
            if not lock.execute("SELECT pg_try_advisory_lock(hashtextextended('cloudsaver:observability-worker',0))").fetchone()[0]:return
        while not stop.is_set():
            if lock:lock.execute('SELECT 1')
            try:
                run_once(settings,lambda:lock.execute('SELECT 1') if lock else None);health.touch()
            except Exception:
                health.touch(False)
                logging.getLogger('cloudsaver.observability').warning('Observability worker iteration unavailable')
            stop.wait(10)
    health.close()

if __name__=='__main__':main()
