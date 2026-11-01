"""Bounded live metadata readers for drift re-inspection (injectable; no import-time cloud I/O)."""
from __future__ import annotations

from typing import Any, Callable


LiveReader = Callable[[dict[str, Any]], dict[str, Any]]


def reader_for_provider(provider: str, *, custom: LiveReader | None = None) -> LiveReader:
    if custom is not None:
        return custom
    if provider == "azure":
        return _azure_reader
    if provider == "aws":
        return _aws_reader
    if provider == "gcp":
        return _gcp_reader
    return lambda _signal: {}


def _azure_reader(signal: dict[str, Any]) -> dict[str, Any]:
    """Production wiring calls Azure ARM read-only clients from app.collectors.azure_live."""
    return dict(
        etag=signal.get("etag"),
        vm_size=signal.get("vm_size"),
        tags=signal.get("tags") or {},
        source="azure_live_stub",
    )


def _aws_reader(signal: dict[str, Any]) -> dict[str, Any]:
    return dict(State=signal.get("State"), tags=signal.get("tags") or {}, source="aws_live_stub")


def _gcp_reader(signal: dict[str, Any]) -> dict[str, Any]:
    return dict(status=signal.get("status"), labels=signal.get("labels") or {}, source="gcp_live_stub")
