"""Runs identity-service access checks on the scanner host."""
import logging
import threading

logger = logging.getLogger('cloudsaver.access_worker')


def enqueue(check_id):
    threading.Thread(target=run, args=(check_id,), name=f'access-check-{check_id[:8]}', daemon=True).start()


def run(check_id):
    from app.identity_client import IdentityUnavailable, shared_client
    from app.access_probe import run_probe
    client = shared_client()
    try:
        claim = client.request('POST', f'/internal/v1/access-checks/{check_id}/claim')
        if claim.status_code == 409:
            return
        if claim.status_code != 200:
            return
        body = claim.json()
        tenant_id = body.get('tenant_id')
        tenant = None
        platform = None
        try:
            from app.config import Settings
            registry = Settings.load().registry
            if registry is not None:
                platform = registry.platform()
                if tenant_id:
                    tenant = registry.get(tenant_id)
        except Exception:
            pass
        result = run_probe(tenant, platform, include_managed_identity=tenant_id is None)
        client.request('PUT', f'/internal/v1/access-checks/{check_id}/result', json=result)
    except IdentityUnavailable:
        logger.warning('Access check skipped because identity-service is unavailable check_id=%s', check_id[:8])
    except Exception:
        logger.warning('Access check failed check_id=%s', check_id[:8])
