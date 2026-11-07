"""Background worker for queued Grafana Kubernetes rightsizing jobs."""
import logging
import os
import signal
import threading

from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.grafana_k8s_store import GrafanaK8sStore


def run_once(settings):
    if os.getenv('CLOUDSAVER_GRAFANA_RIGHTSIZING_WORKER', 'true').lower() != 'true':
        return 0
    repo = GrafanaK8sStore(EnterpriseStore(settings))
    processed = 0
    for tenant in settings.tenants:
        tid = tenant['tenant_id']
        try:
            if repo.claim_next(tid):
                processed += 1
        except Exception:
            logging.getLogger('cloudsaver.grafana_rightsizing').warning('grafana rightsizing worker iteration failed', exc_info=True)
    return processed


def main():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    settings = Settings.load()
    from workers.health import WorkerHealth
    health = WorkerHealth().start()
    while not stop.is_set():
        try:
            run_once(settings)
            health.touch()
        except Exception:
            health.touch(False)
        stop.wait(10)
    health.close()


if __name__ == '__main__':
    main()
