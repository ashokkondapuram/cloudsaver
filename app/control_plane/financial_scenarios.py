"""Commitment-aware scenario math. Exact Decimal money; unknown inputs stay unknown."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
import re
from typing import Optional


def money(value) -> Decimal:
    if type(value) not in (str, int, Decimal) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,4})?", str(value)):
        raise ValueError("Use a nonnegative decimal string with at most 15 integer and 4 fractional digits")
    return Decimal(str(value))


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
    if not isinstance(s.currency, str) or not re.fullmatch(r"[A-Z]{3}", s.currency):
        raise ValueError("Currency must be a three-letter uppercase code")
    if type(s.absorption_proven) is not bool:
        raise ValueError("Absorption must be a boolean resolved from approved evidence")
    for value in (s.commitment_fee, s.uncommitted_baseline, s.uncommitted_if_absorbed, s.new_recurring, s.one_time):
        if value is not None:
            money(value)
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
    with localcontext() as context:
        context.prec = 50
        baseline = fee + base_use
        post = fee + post_use + new_rec
        benefit = baseline - post
    return {
        "status": "computed",
        "currency": s.currency,
        "baseline_payable": str(baseline),
        "post_payable": str(post),
        "net_recurring_benefit": str(benefit),
        "one_time_cost": str(one_time),
        "absorption_proven": s.absorption_proven,
    }


def dedupe_commitments(snapshots: list[dict]) -> list[dict]:
    """Deduplicate by (billing_identity, commitment_id); never double count shared inventory."""
    seen: dict[tuple, dict] = {}
    for snap in snapshots:
        key = (snap.get("provider"), snap["billing_identity"], snap["commitment_id"])
        if any(not isinstance(part, str) or not part for part in key[1:]):
            raise ValueError("Commitment billing identity and identifier are required")
        if key in seen and seen[key] != snap:
            raise ValueError("Conflicting shared commitment snapshots require reconciliation")
        seen.setdefault(key, snap)
    return list(seen.values())
