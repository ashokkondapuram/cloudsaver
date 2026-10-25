"""Commitment expiry reminders. Creates review work items only; never purchases or renews."""
from __future__ import annotations

from datetime import date

DEFAULT_THRESHOLDS = (90, 60, 30)


def due_reminders(commitments: list[dict], today: date, thresholds=DEFAULT_THRESHOLDS,
                  already_sent: set | None = None) -> list[dict]:
    sent = already_sent or set()
    out = []
    for c in commitments:
        end = c.get("end_date")
        if end is None:
            continue
        days = (end - today).days
        if days < 0:
            continue
        crossed = [t for t in thresholds if days <= t]
        if crossed:
            t = min(crossed)
            if (c["commitment_id"], t) in sent:
                continue
            out.append({"commitment_id": c["commitment_id"], "threshold_days": t,
                        "days_remaining": days, "action": "review_work_item"})
    return out
