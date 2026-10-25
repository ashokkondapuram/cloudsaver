"""Versioned plans, conflict detection and exact-version approval binding."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

STATES = ("draft", "evidence_required", "assessed", "review_requested", "approved", "queued",
          "running", "verification_pending", "verified", "failed", "reconciliation_required",
          "cancelled", "expired")


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class PlanVersion:
    plan_id: str
    version: int
    targets: tuple
    parameters: dict
    policy_digest: str
    evidence_digest: str
    exclusive_targets: tuple = ()
    consumes_ha_headroom: tuple = ()
    skus: dict = field(default_factory=dict)  # target -> proposed sku

    def identity(self) -> str:
        return digest({"p": self.plan_id, "v": self.version, "t": sorted(self.targets),
                       "a": self.parameters, "pol": self.policy_digest, "ev": self.evidence_digest})


def detect_conflicts(plans: list[PlanVersion]) -> list[dict]:
    out, claimed, headroom = [], {}, {}
    for p in plans:
        for t in p.exclusive_targets:
            if t in claimed and claimed[t] != p.plan_id:
                out.append({"type": "shared_resource_claimed", "target": t, "plans": [claimed[t], p.plan_id]})
            claimed.setdefault(t, p.plan_id)
        for h in p.consumes_ha_headroom:
            if h in headroom and headroom[h] != p.plan_id:
                out.append({"type": "ha_headroom_contention", "target": h, "plans": [headroom[h], p.plan_id]})
            headroom.setdefault(h, p.plan_id)
    for i, a in enumerate(plans):
        for b in plans[i + 1:]:
            for t, sku in a.skus.items():
                if t in b.skus and b.skus[t] != sku and a.plan_id != b.plan_id:
                    out.append({"type": "exclusive_sku_additive", "target": t, "plans": [a.plan_id, b.plan_id]})
    return out


@dataclass(frozen=True)
class Approval:
    plan_identity: str
    approver: str
    expires_at: datetime
    verified_human: bool = True


def approval_valid(approval: Approval, plan: PlanVersion, now: datetime | None = None,
                   revoked: frozenset = frozenset()) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    if not approval.verified_human:
        return False, "approver is not a verified human"
    if approval.approver in revoked:
        return False, "approver revoked"
    if approval.expires_at <= now:
        return False, "approval expired"
    if approval.plan_identity != plan.identity():
        return False, "plan version, parameters, policy or evidence changed"
    return True, "ok"
