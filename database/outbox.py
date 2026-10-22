"""
In-memory outbox test foundation. Not transactional or durable; not used by production workers.
"""
import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from enum import Enum
from pydantic import BaseModel, Field

logger = logging.getLogger("cloudsaver.outbox")

class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"

class OutboxRecord(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    scan_id: str
    channel: str = "webhook"
    destination_url: Optional[str] = None
    payload: Dict[str, Any]
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    max_attempts: int = 5
    created_at: float = Field(default_factory=time.time)
    last_attempt_at: Optional[float] = None
    next_retry_at: Optional[float] = None
    error_message: Optional[str] = None

class OutboxStore:
    def __init__(self):
        self._records: Dict[str, OutboxRecord] = {}

    def enqueue(
        self,
        tenant_id: str,
        scan_id: str,
        payload: Dict[str, Any],
        channel: str = "slack",
        destination_url: Optional[str] = None,
        max_attempts: int = 5
    ) -> OutboxRecord:
        record = OutboxRecord(
            tenant_id=tenant_id,
            scan_id=scan_id,
            channel=channel,
            destination_url=destination_url,
            payload=payload,
            max_attempts=max_attempts,
            next_retry_at=time.time()
        )
        self._records[record.event_id] = record
        return record

    def fetch_pending(self, limit: int = 20) -> List[OutboxRecord]:
        now = time.time()
        pending = [
            r for r in self._records.values()
            if r.status in (OutboxStatus.PENDING, OutboxStatus.FAILED)
            and (r.next_retry_at is None or r.next_retry_at <= now)
            and r.attempts < r.max_attempts
        ]
        return sorted(pending, key=lambda r: r.created_at)[:limit]

    def mark_dispatched(self, event_id: str) -> None:
        record = self._records.get(event_id)
        if record:
            record.status = OutboxStatus.DISPATCHED
            record.last_attempt_at = time.time()
            record.error_message = None

    def mark_failed(self, event_id: str, error_message: str, backoff_multiplier: float = 2.0) -> None:
        record = self._records.get(event_id)
        if record:
            record.attempts += 1
            record.last_attempt_at = time.time()
            record.error_message = error_message
            if record.attempts >= record.max_attempts:
                record.status = OutboxStatus.DEAD_LETTER
                record.next_retry_at = None
            else:
                record.status = OutboxStatus.FAILED
                delay = (backoff_multiplier ** record.attempts) * 5.0
                record.next_retry_at = time.time() + delay

outbox_store = OutboxStore()
