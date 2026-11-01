"""Processor approval, allowlists, and secret scrubbing gate for Azure AI calls."""
from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)


def scrub_secrets(text: str) -> str:
    cleaned = text
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned


def assert_processor_allowed(tenant: dict, *, purpose: str, payload: dict[str, Any]) -> None:
    if tenant.get("ai_enabled") is False:
        raise PermissionError("AI processing is disabled for this workspace")
    allowed = tenant.get("ai_purposes") or ["drift_classification", "investigation"]
    if purpose not in allowed:
        raise PermissionError("AI purpose is not approved")
    blob = scrub_secrets(str(payload))
    if blob != str(payload):
        raise ValueError("Payload contained disallowed secret material")


def allowlisted_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {k: payload[k] for k in fields if k in payload}
