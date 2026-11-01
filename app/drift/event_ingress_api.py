"""Authenticated and webhook drift cloud-event ingress."""
from __future__ import annotations

import base64
import hmac
import json
import os
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.drift.outbox_store import OUTBOX_KIND_DRIFT, PlatformOutboxStore, drift_idempotency_key
from app.drift.workspace_resolver import workspace_resolver_for_settings
from app.collectors.event_stream import EventStreamConsumer
from app.gitops_api import bounded_json

MAX_INGRESS_EVENTS = 100


def _webhook_secret_ok(request: Request, raw: dict | None = None) -> bool:
    expected = os.getenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET") or ""
    if not expected:
        return False
    provided = request.headers.get("X-CloudSaver-Drift-Webhook-Secret") or ""
    if provided and hmac.compare_digest(provided, expected):
        return True
    if isinstance(raw, dict):
        attrs = (raw.get("message") or {}).get("attributes") or {}
        pushed = attrs.get("webhook_secret") or ""
        if pushed and hmac.compare_digest(pushed, expected):
            return True
    return False


def _parse_ingress_payload(raw: dict) -> tuple[str, list]:
    if isinstance(raw.get("message"), dict) and raw["message"].get("data"):
        payload = json.loads(base64.b64decode(str(raw["message"]["data"])))
        if not isinstance(payload, dict):
            raise ValueError("Pub/Sub audit payload must be an object")
        return "gcp", [payload]
    if raw.get("detail-type") and "events" not in raw:
        return "aws", [raw]
    if "provider" not in raw or "events" not in raw:
        raise ValueError("Provide provider and events array")
    provider = str(raw["provider"])
    events = raw["events"]
    if not isinstance(events, list) or not events:
        raise ValueError("events must be a non-empty array")
    if len(events) > MAX_INGRESS_EVENTS:
        raise ValueError(f"At most {MAX_INGRESS_EVENTS} events per request")
    return provider, events


def _normalize_batch(stream: EventStreamConsumer, provider: str, events: list):
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
        payload = signal.model_dump()
        key = drift_idempotency_key(payload)
        by_tenant[signal.workspace_id].append((OUTBOX_KIND_DRIFT, key, payload))
    return validation_responses, by_tenant


def create_router(settings, evidence_store):
    router = APIRouter(tags=["Drift ingress"])

    def consumer():
        return EventStreamConsumer(workspace_resolver_for_settings(settings))

    @router.post("/api/v1/drift/cloud-events/ingest", status_code=202)
    async def ingest_cloud_events(request: Request):
        raw = await bounded_json(request)
        if not isinstance(raw, dict):
            raise HTTPException(422, "Invalid JSON body")
        if not _webhook_secret_ok(request, raw):
            raise HTTPException(401, "Invalid or missing drift webhook secret")
        try:
            provider, events = _parse_ingress_payload(raw)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

        def process():
            stream = consumer()
            validation_responses, by_tenant = _normalize_batch(stream, provider, events)
            outbox = PlatformOutboxStore(evidence_store)
            queued = []
            for tenant_id, rows in by_tenant.items():
                queued.extend(outbox.enqueue_batch(tenant_id, rows))
            result = dict(accepted=len(queued), intents=queued)
            if validation_responses:
                result["validation"] = validation_responses[0]
            return result

        try:
            return await run_in_threadpool(process)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
