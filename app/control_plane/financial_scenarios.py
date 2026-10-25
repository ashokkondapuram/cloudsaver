"""Commitment-aware scenario math. Exact Decimal money; unknown inputs stay unknown."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional


def money(value) -> Decimal:
    if isinstance(value, float):
        raise ValueError("floats are not accepted for money; use strings or Decimal")
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid money value") from exc
    if not d.is_finite() or d < 0:
        raise ValueError("money must be finite and non-negative")
    return d


@dataclass(frozen=True)
class ScenarioInput:
    currency: str
    commitment_fee: Optional[str]          # unchanged contractual fee per period
    uncommitted_baseline: Optional[str]    # payable usage charges before change
    uncommitted_if_absorbed: Optional[str] # usage charges if released benefit is absorbed
    absorption_proven: bool = False        # evidence that released benefit covers eligible usage
    new_recurring: str = "0"
    one_time: str = "0"


def evaluate(s: ScenarioInput) -> dict:
    """Return payable baseline/post totals and net benefit, or status=unknown."""
    if not s.currency:
        return {"status": "unknown", "reason": "missing currency"}
    if s.commitment_fee is None or s.uncommitted_baseline is None:
        return {"status": "unknown", "reason": "missing commitment or charge coverage"}
    fee = money(s.commitment_fee)
    base_use = money(s.uncommitted_baseline)
    new_rec = money(s.new_recurring)
    one_time = money(s.one_time)
    if s.absorption_proven:
        if s.uncommitted_if_absorbed is None:
            return {"status": "unknown", "reason": "absorption claimed without absorbed usage estimate"}
        post_use = money(s.uncommitted_if_absorbed)
    else:
        post_use = base_use
    baseline = fee + base_use
    post = fee + post_use + new_rec
    return {
        "status": "computed",
        "currency": s.currency,
        "baseline_payable": str(baseline),
        "post_payable": str(post),
        "net_recurring_benefit": str(baseline - post),
        "one_time_cost": str(one_time),
        "absorption_proven": s.absorption_proven,
    }


def dedupe_commitments(snapshots: list[dict]) -> list[dict]:
    """Deduplicate by (billing_identity, commitment_id); never double count shared inventory."""
    seen: dict[tuple, dict] = {}
    for snap in snapshots:
        key = (snap["billing_identity"], snap["commitment_id"])
        seen.setdefault(key, snap)
    return list(seen.values())
