"""Governed Azure OpenAI drift classification (optional; processor-guarded)."""
from __future__ import annotations

from typing import Any


def classify_drift(
    tenant: dict,
    *,
    baseline: dict[str, Any],
    live: dict[str, Any],
    drifted_fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Return structured classification when AI governance allows; otherwise None."""
    if not drifted_fields:
        return None
    if not tenant.get("ai_enabled"):
        return dict(
            source="deterministic",
            category="operational_change",
            summary="Structural operational drift detected without AI classification.",
        )
    return dict(
        source="azure_openai",
        category="pending_review",
        summary="Drift diff queued for governed Azure OpenAI classification.",
        allowlisted_fields=sorted(drifted_fields.keys()),
    )
