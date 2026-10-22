"""
Legacy in-memory lease/state test double; production uses workers.tasks.RedisLease.
"""
import time
import logging
from typing import Dict, Any, Optional, Set
from enum import Enum

logger = logging.getLogger("cloudsaver.lease")

class JobLifecycleState(str, Enum):
    QUEUED = "QUEUED"
    LEASE_ACQUIRED = "LEASE_ACQUIRED"
    SCANNING_ARG = "SCANNING_ARG"
    ATTRIBUTING_PRICES = "ATTRIBUTING_PRICES"
    PERSISTING = "PERSISTING"
    OUTBOX_COMMITTED = "OUTBOX_COMMITTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

class DistributedLeaseManager:
    def __init__(self, default_ttl_seconds: int = 600):
        self.default_ttl = default_ttl_seconds
        self._leases: Dict[str, Dict[str, Any]] = {}
        self._cancellation_requests: Set[str] = set()
        self._job_states: Dict[str, JobLifecycleState] = {}

    def acquire_lease(self, resource_key: str, owner_id: str, ttl_seconds: Optional[int] = None) -> bool:
        now = time.time()
        ttl = ttl_seconds or self.default_ttl

        existing = self._leases.get(resource_key)
        if existing and existing["expires_at"] > now:
            if existing["owner_id"] == owner_id:
                existing["expires_at"] = now + ttl
                return True
            return False

        self._leases[resource_key] = {
            "owner_id": owner_id,
            "acquired_at": now,
            "expires_at": now + ttl
        }
        return True

    def renew_lease(self, resource_key: str, owner_id: str, ttl_seconds: Optional[int] = None) -> bool:
        now = time.time()
        ttl = ttl_seconds or self.default_ttl
        existing = self._leases.get(resource_key)
        if not existing or existing["owner_id"] != owner_id or existing["expires_at"] <= now:
            return False
        existing["expires_at"] = now + ttl
        return True

    def release_lease(self, resource_key: str, owner_id: str) -> bool:
        existing = self._leases.get(resource_key)
        if existing and existing["owner_id"] == owner_id:
            del self._leases[resource_key]
            return True
        return False

    def request_cancellation(self, job_id: str) -> None:
        self._cancellation_requests.add(job_id)
        self.update_job_state(job_id, JobLifecycleState.CANCELLED)

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancellation_requests

    def update_job_state(self, job_id: str, state: JobLifecycleState) -> None:
        self._job_states[job_id] = state

    def get_job_state(self, job_id: str) -> JobLifecycleState:
        return self._job_states.get(job_id, JobLifecycleState.QUEUED)

lease_manager = DistributedLeaseManager()


class LeaseLost(RuntimeError):
    pass


class LeaseHeartbeat:
    """Renew an owned Redis lease and fail closed before committing results."""
    def __init__(self, lease, tenant_id, token, interval=30):
        from threading import Event, Thread
        self.lease, self.tenant_id, self.token = lease, tenant_id, token
        self.interval = interval
        self.finished, self.lost = Event(), Event()
        self.thread = Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.finished.wait(self.interval):
            try:
                self.ensure_owned()
            except LeaseLost:
                return

    def start(self):
        self.thread.start()

    def ensure_owned(self):
        try:
            if self.lost.is_set() or not self.lease.renew(self.tenant_id, self.token):
                raise LeaseLost('Workspace lease was lost')
        except Exception:
            self.lost.set()
            raise LeaseLost('Workspace lease was lost') from None

    def stop(self):
        self.finished.set()
        self.thread.join(timeout=6)
