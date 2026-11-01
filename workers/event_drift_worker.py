"""Process CloudDriftSignal outbox intents with Redis burst deduplication."""
from __future__ import annotations

import os
import secrets

from app.collectors.event_stream import EventStreamConsumer
from app.drift.drift_manager import abort_agent_permits_for_drift, inspect_resource, stage_gitops_drift_flag
from app.drift.outbox_store import PlatformOutboxStore
from app.gitops_ast_mapper import GitOpsAstMapper
from workers.named_lease import NamedRedisLease, drift_inspect_lease_key


def process_drift_intent(
    intent: dict,
    *,
    outbox: PlatformOutboxStore,
    agent_repo=None,
    baseline_loader=None,
    live_reader=None,
    lease: NamedRedisLease | None = None,
    mapper: GitOpsAstMapper | None = None,
) -> dict:
    payload = intent["payload"]
    workspace_id = payload["workspace_id"]
    resource_hash = EventStreamConsumer.resource_hash(payload["canonical_resource_id"])
    token = secrets.token_hex(8)
    key = drift_inspect_lease_key(workspace_id, resource_hash)
    lease = lease or NamedRedisLease(os.getenv("REDIS_URL", "redis://redis:6379/1"), ttl=30)
    if not lease.acquire(key, token):
        return dict(skipped=True, reason="lease_busy")
    try:
        baseline = (baseline_loader or (lambda _signal: {}))(payload)
        reader = live_reader or (lambda _signal: {})
        result = inspect_resource(payload, baseline=baseline, live_reader=reader)
        actions: dict = dict(drifted=result.drifted, reasons=result.reasons)
        if result.drifted and agent_repo is not None:
            actions["agent_permits_aborted"] = abort_agent_permits_for_drift(
                agent_repo, workspace_id, payload["canonical_resource_id"]
            )
        if result.drifted:
            mapping = None
            try:
                row = (mapper or GitOpsAstMapper()).lookup(payload["canonical_resource_id"])
                mapping = row.model_dump()
            except KeyError:
                pass
            actions["gitops"] = stage_gitops_drift_flag(mapping)
        outbox.complete(workspace_id, intent["id"])
        return actions
    except Exception:
        outbox.fail(workspace_id, intent["id"], "inspect_failed")
        raise
    finally:
        lease.release(key, token)


def dispatch_pending_drift(outbox: PlatformOutboxStore, tenant_id: str, **kwargs) -> list[dict]:
    intents = outbox.claim_pending(tenant_id, "DRIFT_INSPECT_RESOURCE")
    return [process_drift_intent(item, outbox=outbox, **kwargs) for item in intents]
