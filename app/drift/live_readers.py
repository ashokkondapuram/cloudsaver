"""Bounded live metadata readers for drift re-inspection (injectable; no import-time cloud I/O)."""
from __future__ import annotations

import os
from typing import Any, Callable


LiveReader = Callable[[dict[str, Any]], dict[str, Any]]


def drift_live_reads_enabled() -> bool:
    return os.getenv("CLOUDSAVER_DRIFT_LIVE_READERS", "false").lower() == "true"


def reader_for_provider(
    provider: str,
    *,
    custom: LiveReader | None = None,
    tenant: dict[str, Any] | None = None,
    use_live: bool | None = None,
) -> LiveReader:
    if custom is not None:
        return custom
    live = drift_live_reads_enabled() if use_live is None else use_live
    if live and tenant is not None:
        if provider == "azure":
            return lambda signal: _azure_live(signal, tenant)
        if provider == "aws":
            return lambda signal: _aws_live(signal, tenant)
        if provider == "gcp":
            return lambda signal: _gcp_live(signal, tenant)
    if provider == "azure":
        return _azure_reader
    if provider == "aws":
        return _aws_reader
    if provider == "gcp":
        return _gcp_reader
    return lambda _signal: {}


def reader_for_signal(signal: dict[str, Any], *, tenant: dict[str, Any] | None = None) -> LiveReader:
    provider = str(signal.get("provider") or "azure")
    return reader_for_provider(provider, tenant=tenant)


def _azure_live(signal: dict[str, Any], tenant: dict[str, Any]) -> dict[str, Any]:
    from app.cloud_identity import CredentialError
    from app.drift.operational_fetch import fetch_azure_operational

    try:
        return fetch_azure_operational(signal, tenant)
    except CredentialError:
        return _azure_reader(signal)
    except Exception:
        return dict(source="azure_live_error", tags=signal.get("tags") or {})


def _aws_live(signal: dict[str, Any], tenant: dict[str, Any]) -> dict[str, Any]:
    from app.cloud_identity import CredentialError
    from app.drift.operational_fetch import fetch_aws_operational

    try:
        return fetch_aws_operational(signal, tenant)
    except CredentialError:
        return _aws_reader(signal)
    except Exception:
        return dict(source="aws_live_error", State=signal.get("State"), tags=signal.get("tags") or {})


def _gcp_live(signal: dict[str, Any], tenant: dict[str, Any]) -> dict[str, Any]:
    from app.cloud_identity import CredentialError
    from app.drift.operational_fetch import fetch_gcp_operational

    try:
        return fetch_gcp_operational(signal, tenant)
    except CredentialError:
        return _gcp_reader(signal)
    except Exception:
        return dict(source="gcp_live_error", labels=signal.get("labels") or {})


def _azure_reader(signal: dict[str, Any]) -> dict[str, Any]:
    """Production wiring calls Azure ARM read-only clients when CLOUDSAVER_DRIFT_LIVE_READERS=true."""
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
