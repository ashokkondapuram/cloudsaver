"""TTL sandbox lease expiry detector staging human-gated teardown plans (v3 scaffold)."""
from __future__ import annotations

from datetime import datetime, timezone


def lease_expired(tags: dict[str, str], *, now: datetime | None = None) -> bool:
    raw = tags.get("cloudsaver:lease-expires-at") or tags.get("cloudsaver:lease_expires_at")
    if not raw:
        return False
    now = now or datetime.now(timezone.utc)
    expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= now


def stage_teardown_plan(resource_id: str, tags: dict[str, str]) -> dict:
    if not lease_expired(tags):
        raise ValueError("Lease has not expired")
    return dict(
        resource_id=resource_id,
        intent="stage_human_approved_teardown",
        automatic_execution=False,
        required_role="TenantAdmin",
        status="awaiting_approval",
    )
