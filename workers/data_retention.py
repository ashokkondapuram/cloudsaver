"""Local database maintenance only; no model, connector, training or export calls."""
import logging,signal,time
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.data_retention import DataRetention


def run_once(settings=None):
    settings=settings or Settings.load();repository=DataRetention(EnterpriseStore(settings))
    # Inactive workspaces still require retention enforcement.
    tenants=settings.registry.all() if settings.registry is not None else settings.bootstrap_tenants
    erased=failed=0
    for tenant in tenants:
        try:erased+=repository.purge(tenant['tenant_id'])
        except Exception:failed+=1
    return dict(erased=erased,failed_workspaces=failed)


def main():
    from workers.health import WorkerHealth
    health=WorkerHealth(max_age=1200).start()
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopped:
        try:
            result=run_once();health.touch(result['failed_workspaces']==0)
            logging.warning('AI content retention result: %s',result)
        except Exception:
            health.touch(False)
            logging.error('AI content retention maintenance failed; operator inspection is required.')
        for _ in range(600):
            if stopped:break
            time.sleep(1)
    health.close()


if __name__=='__main__':main()
