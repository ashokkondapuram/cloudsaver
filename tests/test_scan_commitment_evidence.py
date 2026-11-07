from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.scan_commitment_evidence import _distribute_charge, attach_commitment_evidence

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def test_distribute_charge_splits_across_hours():
    start = NOW - timedelta(days=1)
    end = NOW
    buckets: dict = {}
    assert _distribute_charge(start, end, Decimal("24"), buckets)
    assert len(buckets) == 24
    assert sum(buckets.values()) == Decimal("24")


class _EmptyStore:
    def transaction(self, _tenant_id):
        class _Tx:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def execute(self, *_args, **_kwargs):
                return self

            def fetchall(self):
                return []

        return _Tx()


def test_attach_skips_without_focus_rows():
    tenant_id = str(uuid4())
    store = _EmptyStore()
    tenant = {
        "tenant_id": tenant_id,
        "subscription_ids": [str(uuid4())],
        "aws_accounts": [],
        "gcp_projects": [],
        "allowed_providers": None,
    }
    scan = {
        "scan_id": str(uuid4()),
        "timestamp": NOW.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "status": "completed",
        "findings": [{"estimated_savings_usd": "7300", "outcome": "condition_detected", "resource_id": "r1"}],
    }
    result = attach_commitment_evidence(tenant, dict(scan), store)
    assert "commitment_evidence" not in result
