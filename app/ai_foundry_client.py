"""Keyless Azure OpenAI / Foundry client boundary (v2/v3 scaffold)."""
from __future__ import annotations

from typing import Any


class AzureAIFoundryClient:
    def __init__(self, *, enabled: bool = False):
        self.enabled = enabled

    def complete(self, tenant: dict, *, purpose: str, payload: dict[str, Any]) -> dict[str, Any]:
        from app.ai_processor_guard import assert_processor_allowed

        assert_processor_allowed(tenant, purpose=purpose, payload=payload)
        if not self.enabled:
            return dict(status="disabled", advisory_only=True)
        return dict(
            status="not_implemented",
            purpose=purpose,
            advisory_only=True,
            reason=(
                "Direct Foundry completion is not available on this boundary. "
                "Use governed AI advisory or resource assessment APIs backed by the inference ledger."
            ),
        )
