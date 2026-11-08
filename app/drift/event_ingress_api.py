"""Authenticated and webhook drift cloud-event ingress.

Each tenant+provider gets its own ingest credential (derived from a platform master secret),
carried in the URL path. The webhook secret/signature is never read from the request body, and
the tenant is never taken from client-declared fields: it comes from the authenticated path, and
every normalized event must resolve (via its cloud account/subscription/project id) to that same
tenant or the whole batch is rejected.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request

from starlette.concurrency import run_in_threadpool

from app.drift.outbox_store import OUTBOX_KIND_DRIFT, PlatformOutboxStore, drift_idempotency_key
from app.drift.workspace_resolver import workspace_resolver_for_settings
from app.collectors.event_stream import EventStreamConsumer

MAX_INGRESS_EVENTS = 100
SIGNATURE_WINDOW_SECONDS = 300
PROVIDERS = ("aws", "azure", "gcp")


class ForeignTenantEvent(Exception):
    """An event resolved to a tenant other than the one the credential authenticated."""


def master_secret() -> str:
    secret = os.getenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET") or ""
    if len(secret) < 16:
        raise ValueError("CLOUDSAVER_DRIFT_WEBHOOK_SECRET must be at least 16 characters")
    return secret


def tenant_ingest_secret(tenant_id: str) -> str:
    """Per-tenant credential derived from the platform master secret. Never stored or sent as-is
    anywhere a customer's cloud project/account can read it back (see cloud_event_subscriptions)."""
    return hmac.new(master_secret().encode(), tenant_id.encode(), "sha256").hexdigest()


def _verify_signature(request: Request, tenant_id: str, body: bytes) -> bool:
    header = request.headers.get("X-CloudSaver-Drift-Signature") or ""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - timestamp) > SIGNATURE_WINDOW_SECONDS:
        return False
    expected = hmac.new(tenant_ingest_secret(tenant_id).encode(), f"{timestamp}.".encode() + body, "sha256").hexdigest()
    return hmac.compare_digest(parts.get("v1", ""), expected)


def _verify_aeg_sas_key(request: Request, tenant_id: str) -> bool:
    provided = request.headers.get("aeg-sas-key") or ""
    return bool(provided) and hmac.compare_digest(provided, tenant_ingest_secret(tenant_id))


def _verify_gcp_oidc(request: Request, ingest_url: str) -> bool:
    """Pub/Sub push authentication: a freshly minted OIDC token, never a static shared secret."""
    authorization = request.headers.get("authorization") or ""
    if not authorization.lower().startswith("bearer "):
        return False
    invoker = os.getenv("CLOUDSAVER_DRIFT_PUBSUB_INVOKER_SA") or ""
    if not invoker:
        return False
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import id_token
        claims = id_token.verify_oauth2_token(authorization[7:].strip(), GoogleAuthRequest(), audience=ingest_url)
    except Exception:
        return False
    return bool(claims.get("email_verified")) and claims.get("email") == invoker


def _authenticated(request: Request, tenant_id: str, provider: str, body: bytes, ingest_url: str) -> bool:
    if provider == "gcp":
        return _verify_gcp_oidc(request, ingest_url) or _verify_signature(request, tenant_id, body)
    if provider == "azure":
        return _verify_aeg_sas_key(request, tenant_id) or _verify_signature(request, tenant_id, body)
    return _verify_signature(request, tenant_id, body)


def _events_for_provider(provider: str, raw) -> list:
    if provider == "gcp":
        if not isinstance(raw, dict) or not isinstance(raw.get("message"), dict) or not raw["message"].get("data"):
            raise ValueError("Invalid Pub/Sub push payload")
        payload = json.loads(base64.b64decode(str(raw["message"]["data"])))
        if not isinstance(payload, dict):
            raise ValueError("Pub/Sub audit payload must be an object")
        return [payload]
    if provider == "aws":
        if not isinstance(raw, dict):
            raise ValueError("AWS event payload must be an object")
        return [raw]
    # Azure Event Grid delivers a top-level JSON array of events (and of the validation event).
    items = raw if isinstance(raw, list) else [raw]
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("Each event must be an object")
    if len(items) > MAX_INGRESS_EVENTS:
        raise ValueError(f"At most {MAX_INGRESS_EVENTS} events per request")
    return items


def _normalize_batch(stream: EventStreamConsumer, provider: str, events: list, tenant_id: str):
    validation_responses = []
    by_tenant: dict[str, list] = defaultdict(list)
    for item in events:
        if not isinstance(item, dict):
            raise ValueError("Each event must be an object")
        if provider == "azure" and item.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            data = item.get("data") or {}
            code = data.get("validationCode") if isinstance(data, dict) else None
            if code:
                validation_responses.append(dict(validationResponse=code))
            continue
        if provider == "azure":
            signal = stream.normalize_eventgrid(item)
        elif provider == "aws":
            signal = stream.normalize_eventbridge(item)
        elif provider == "gcp":
            signal = stream.normalize_gcp_audit(item)
        else:
            raise ValueError("Unsupported provider")
        if signal.workspace_id != tenant_id:
            # The credential authenticated tenant_id; an event naming another tenant's account is
            # never enqueued, for any tenant, even if the forged account id happens to be real.
            raise ForeignTenantEvent()
        payload = signal.model_dump()
        key = drift_idempotency_key(payload)
        by_tenant[signal.workspace_id].append((OUTBOX_KIND_DRIFT, key, payload))
    return validation_responses, by_tenant


def create_router(settings, evidence_store):
    router = APIRouter(tags=["Drift ingress"])

    def consumer():
        return EventStreamConsumer(workspace_resolver_for_settings(settings))

    @router.post("/api/v1/drift/cloud-events/ingest/{tenant_id}/{provider}", status_code=202)
    async def ingest_cloud_events(tenant_id: str, provider: str, request: Request):
        if provider not in PROVIDERS:
            raise HTTPException(404, "Unknown provider")
        if tenant_id not in {str(t["tenant_id"]) for t in settings.tenants}:
            raise HTTPException(403, "Invalid or missing drift ingest credential")
        body = await request.body()
        if len(body) > 1_000_000:
            raise HTTPException(422, "Request body too large")
        ingest_url = str(request.url).split("?", 1)[0]
        if not _authenticated(request, tenant_id, provider, body, ingest_url):
            raise HTTPException(403, "Invalid or missing drift ingest credential")
        try:
            raw = json.loads(body) if body else None
        except ValueError:
            raise HTTPException(422, "Invalid JSON body") from None
        try:
            events = _events_for_provider(provider, raw)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

        def process():
            stream = consumer()
            validation_responses, by_tenant = _normalize_batch(stream, provider, events, tenant_id)
            outbox = PlatformOutboxStore(evidence_store)
            queued = []
            for tid, rows in by_tenant.items():
                queued.extend(outbox.enqueue_batch(tid, rows))
            result = dict(accepted=len(queued), intents=queued)
            if validation_responses:
                result["validation"] = validation_responses[0]
            return result

        try:
            return await run_in_threadpool(process)
        except ForeignTenantEvent:
            raise HTTPException(403, "Event does not belong to this tenant") from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
