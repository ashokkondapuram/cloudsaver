"""Authenticated and webhook drift cloud-event ingress."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.drift.outbox_store import PlatformOutboxStore
from app.drift.workspace_resolver import workspace_resolver_for_settings
from app.collectors.event_stream import EventStreamConsumer
from app.gitops_api import bounded_json


def _webhook_secret_ok(request: Request) -> bool:
    expected = os.getenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET") or ""
    if not expected:
        return False
    provided = request.headers.get("X-CloudSaver-Drift-Webhook-Secret") or ""
    return hmac.compare_digest(provided, expected)


def create_router(settings, evidence_store):
    router = APIRouter(tags=["Drift ingress"])

    def consumer():
        return EventStreamConsumer(workspace_resolver_for_settings(settings))

    @router.post("/api/v1/drift/cloud-events/ingest", status_code=202)
    async def ingest_cloud_events(request: Request):
        if not _webhook_secret_ok(request):
            raise HTTPException(401, "Invalid or missing drift webhook secret")
        raw = await bounded_json(request)
        if not isinstance(raw, dict) or "provider" not in raw or "events" not in raw:
            raise HTTPException(422, "Provide provider and events array")
        provider = str(raw["provider"])
        events = raw["events"]
        if not isinstance(events, list) or not events:
            raise HTTPException(422, "events must be a non-empty array")

        def process():
            stream = consumer()
            outbox = PlatformOutboxStore(evidence_store)
            queued = []
            for item in events[:100]:
                if not isinstance(item, dict):
                    raise ValueError("Each event must be an object")
                if provider == "azure":
                    signal = stream.normalize_eventgrid(item)
                elif provider == "aws":
                    signal = stream.normalize_eventbridge(item)
                elif provider == "gcp":
                    signal = stream.normalize_gcp_audit(item)
                else:
                    raise ValueError("Unsupported provider")
                queued.append(stream.enqueue_drift_inspect(outbox, signal))
            return dict(accepted=len(queued), intents=queued)

        try:
            return await run_in_threadpool(process)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
