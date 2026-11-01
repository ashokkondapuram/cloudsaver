"""Compare live cloud metadata to saved baselines and coordinate remediation flags."""
from __future__ import annotations

from typing import Any, Callable

from app.drift.baseline_store import baseline_hash

LiveReader = Callable[[dict[str, Any]], dict[str, Any]]


class DriftInspectionResult:
    def __init__(self, *, drifted: bool, live: dict[str, Any], baseline: dict[str, Any], reasons: list[str]):
        self.drifted = drifted
        self.live = live
        self.baseline = baseline
        self.reasons = reasons


def live_state_hash(live: dict[str, Any]) -> str:
    return baseline_hash(live)


def compare_all_operational_keys(baseline: dict[str, Any], live: dict[str, Any]) -> DriftInspectionResult:
    keys = sorted(set(baseline) | set(live))
    reasons = []
    drifted_fields = {}
    for key in keys:
        if baseline.get(key) != live.get(key):
            reasons.append(f"{key}_mismatch")
            drifted_fields[key] = dict(baseline=baseline.get(key), live=live.get(key))
    return DriftInspectionResult(
        drifted=bool(reasons),
        live=live,
        baseline=baseline,
        reasons=reasons,
    )


def compare_operational_state(
    baseline: dict[str, Any],
    live: dict[str, Any],
    *,
    fields: tuple[str, ...] = ("vm_size", "disk_size_gb", "sku", "etag", "tags"),
) -> DriftInspectionResult:
    reasons: list[str] = []
    for field in fields:
        if field in baseline or field in live:
            if baseline.get(field) != live.get(field):
                reasons.append(f"{field}_mismatch")
    return DriftInspectionResult(
        drifted=bool(reasons),
        live=live,
        baseline=baseline,
        reasons=reasons,
    )


def inspect_resource(
    signal: dict[str, Any],
    *,
    baseline: dict[str, Any],
    live_reader: LiveReader,
    zero_tolerance: bool = True,
) -> DriftInspectionResult:
    live = live_reader(signal)
    if zero_tolerance and baseline:
        return compare_all_operational_keys(baseline, live)
    return compare_operational_state(baseline, live)


def abort_agent_permits_for_drift(agent_repo, tenant_id: str, resource_id: str) -> int:
    """Mark in-flight approved agent tasks as drift-aborted (ABORTED_STATE_DRIFT)."""
    from app.enterprise_store import decode

    aborted = 0
    with agent_repo.store.transaction(tenant_id, write=True) as db:
        rows = db.execute(
            """SELECT id,payload,state FROM agent_tasks
               WHERE tenant_id=%s AND lower(resource_id)=lower(%s) AND state IN ('approved','running')""",
            (tenant_id, resource_id),
        ).fetchall()
        for task_id, payload, state in rows:
            body = decode(payload)
            body["permit_status"] = "ABORTED_STATE_DRIFT"
            db.execute(
                "UPDATE agent_tasks SET state='cancelled',payload=%s WHERE tenant_id=%s AND id=%s",
                (db.json(body), tenant_id, str(task_id)),
            )
            aborted += 1
    return aborted


def stage_gitops_drift_flag(mapping: dict[str, Any] | None) -> dict[str, Any] | None:
    if not mapping:
        return None
    return dict(
        status="DRIFTED_FROM_IAC",
        repository=mapping.get("repository"),
        file_path=mapping.get("file_path"),
        address=mapping.get("address"),
    )
