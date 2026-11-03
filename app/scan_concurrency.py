"""Workspace scan mutual exclusion across API replicas and Celery workers."""
import os


def distributed_scan_lock_enabled():
    return os.getenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', '').lower() == 'true'


def distributed_scan_lease_held(tenant_id):
    if not distributed_scan_lock_enabled():
        return False
    from workers.tasks import RedisLease
    lease = RedisLease(os.getenv('REDIS_URL', 'redis://redis:6379/1'))
    try:
        return lease.held(tenant_id)
    finally:
        lease.close()


SCAN_LEASE_BUSY = 'A scan is already running for this workspace (distributed lease held)'
