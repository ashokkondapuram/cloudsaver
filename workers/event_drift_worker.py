"""Process CloudDriftSignal outbox intents with Redis burst deduplication."""
from __future__ import annotations

import os
import secrets

from app.collectors.event_stream import EventStreamConsumer
from app.drift.azure_ai_drift_explainer import classify_drift
from app.drift.baseline_store import BaselineStore
from app.drift.drift_manager import (
    abort_agent_permits_for_drift,
    compare_all_operational_keys,
    inspect_resource,
    live_state_hash,
    stage_gitops_drift_flag,
)
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
    baseline_store: BaselineStore | None = None,
    tenant_loader=None,
) -> dict:
    payload = intent["payload"]
    workspace_id = payload["workspace_id"]
    resource_hash = EventStreamConsumer.resource_hash(payload["canonical_resource_id"])
    token = secrets.token_hex(8)
    key = drift_inspect_lease_key(workspace_id, resource_hash)
    lease = lease or NamedRedisLease(os.getenv("REDIS_URL", "redis://redis:6379/1"), ttl=30)
    if not lease.acquire(key, token):
        outbox.release_to_pending(
            workspace_id, intent["id"], intent["lease_owner"], intent["lease_fence"]
        )
        return dict(skipped=True, reason="lease_busy")
    try:
        outbox.renew_lease(workspace_id, intent["id"], intent["lease_owner"], intent["lease_fence"])
        baseline_row = None
        if baseline_store is not None:
            baseline_row = baseline_store.get_baseline(workspace_id, payload["canonical_resource_id"])
        baseline = (
            baseline_row["expected_state"]
            if baseline_row
            else (baseline_loader or (lambda _signal: {}))(payload)
        )
        reader = live_reader or (lambda _signal: {})
        result = inspect_resource(payload, baseline=baseline, live_reader=reader, zero_tolerance=bool(baseline))
        actions: dict = dict(drifted=result.drifted, reasons=result.reasons)
        if result.drifted and agent_repo is not None:
            actions["agent_permits_aborted"] = abort_agent_permits_for_drift(
                agent_repo, workspace_id, payload["canonical_resource_id"]
            )
            permit_action = "ABORTED_STATE_DRIFT"
        else:
            permit_action = None
        drifted_fields = {}
        if result.drifted and baseline:
            diff = compare_all_operational_keys(baseline, result.live)
            drifted_fields = {r.replace("_mismatch", ""): True for r in diff.reasons}
        if result.drifted and baseline_store is not None:
            tenant = (tenant_loader or (lambda _id: {}))(workspace_id)
            ai = classify_drift(tenant, baseline=baseline, live=result.live, drifted_fields=drifted_fields)
            baseline_store.record_drift_event(
                workspace_id,
                canonical_resource_id=payload["canonical_resource_id"],
                provider=payload.get("provider", "azure"),
                operation=payload.get("operation", "unknown"),
                actor_principal=payload.get("actor_principal", "unknown"),
                baseline_hash_value=baseline_row["baseline_hash"] if baseline_row else None,
                live_hash_value=live_state_hash(result.live),
                drifted_fields=drifted_fields,
                permit_action=permit_action,
                ai_classification=ai,
            )
        if result.drifted:
            mapping = None
            try:
                row = (mapper or GitOpsAstMapper()).lookup(payload["canonical_resource_id"])
                mapping = row.model_dump()
            except KeyError:
                pass
            actions["gitops"] = stage_gitops_drift_flag(mapping)
        outbox.complete(
            workspace_id,
            intent["id"],
            lease_owner=intent["lease_owner"],
            lease_fence=intent["lease_fence"],
        )
        return actions
    except Exception:
        outbox.fail(
            workspace_id,
            intent["id"],
            "inspect_failed",
            lease_owner=intent["lease_owner"],
            lease_fence=intent["lease_fence"],
            recoverable=True,
        )
        raise
    finally:
        lease.release(key, token)


def dispatch_pending_drift(outbox: PlatformOutboxStore, tenant_id: str, **kwargs) -> list[dict]:
    worker_id = secrets.token_hex(16)
    intents = outbox.claim_pending(tenant_id, "DRIFT_INSPECT_RESOURCE", owner=worker_id)
    results = []
    for item in intents:
        try:
            results.append(process_drift_intent(item, outbox=outbox, **kwargs))
        except Exception as exc:
            results.append(dict(intent_id=item["id"], error=type(exc).__name__))
    return results
