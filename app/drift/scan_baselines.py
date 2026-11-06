"""Capture scan inventory as drift baselines and flag non-IaC activity on evidence."""
from __future__ import annotations

from typing import Any

from app.collectors.activity_events import is_iac_authorized
from app.domain.resource.identity import canonical_resource_id

_EVIDENCE_BASELINE_SKIP = frozenset(
    {
        'metrics',
        'state_history',
        'activity_events',
        'analysis_readiness',
        'metric_summaries',
        'observed_signals',
        'typed_configuration',
    }
)


def human_activity_drift(evidence: dict | None) -> bool:
    if not isinstance(evidence, dict):
        return False
    for item in evidence.get('activity_events') or []:
        if not isinstance(item, dict):
            continue
        if item.get('is_iac_authorized') is False:
            return True
        actor = item.get('actor_identity')
        if actor and not is_iac_authorized(str(actor)):
            return True
    return False


def apply_drift_detected(row: dict) -> bool:
    """Set evidence.drift_detected when Stream D shows non-IaC mutations."""
    evidence = row.setdefault('evidence', {})
    if not isinstance(evidence, dict):
        return False
    if human_activity_drift(evidence):
        evidence['drift_detected'] = True
    return bool(evidence.get('drift_detected'))


def expected_state_from_inventory(row: dict) -> dict[str, Any]:
    """Operational baseline aligned with drift live readers and agent inspect contracts."""
    from app.agent_contract import expected_state as agent_expected

    evidence = row.get('evidence') if isinstance(row.get('evidence'), dict) else {}
    snapshot = row.get('configuration_snapshot') if isinstance(row.get('configuration_snapshot'), dict) else {}
    merged: dict[str, Any] = {}
    for source in (snapshot, evidence):
        for key, value in source.items():
            if key in _EVIDENCE_BASELINE_SKIP or value is None:
                continue
            merged[key] = value

    state: dict[str, Any] = dict(agent_expected({**row, 'evidence': merged}))
    tags = merged.get('tags') or merged.get('labels')
    if isinstance(tags, dict):
        state['tags'] = tags
    labels = merged.get('labels')
    if isinstance(labels, dict):
        state.setdefault('labels', labels)

    for key in (
        'etag',
        'vm_size',
        'disk_size_gb',
        'sku',
        'sku_name',
        'instance_type',
        'instance_class',
        'machine_type',
        'State',
        'status',
        'volume_type',
    ):
        if key in merged and merged[key] is not None:
            state[key] = merged[key]
    if 'sku' not in state and isinstance(state.get('sku_name'), str):
        state['sku'] = state.pop('sku_name')
    return state


def capture_scan_drift_baselines(
    scan: dict,
    *,
    tenant_id: str,
    baseline_store=None,
    now: str | None = None,
) -> dict:
    """Mutate scan inventory evidence and upsert baselines for each resource row."""
    inventory = scan.get('inventory') or []
    captured_at = now or scan.get('timestamp')
    stats = dict(baselines=0, drift_detected=0, skipped_empty=0)
    for row in inventory:
        if not isinstance(row, dict) or not row.get('resource_id'):
            continue
        if apply_drift_detected(row):
            stats['drift_detected'] += 1
        expected = expected_state_from_inventory(row)
        if not expected:
            stats['skipped_empty'] += 1
            continue
        if baseline_store is None:
            stats['baselines'] += 1
            continue
        provider = row.get('cloud_provider') or row.get('provider') or 'azure'
        canonical_id = canonical_resource_id(provider, row['resource_id'])
        baseline_store.upsert_baseline(tenant_id, canonical_id, provider, expected, now=captured_at)
        stats['baselines'] += 1
    return stats


def _baseline_store_for_settings(settings):
    url = getattr(settings, 'database_url', None) or ''
    if not url.startswith(('postgresql://', 'postgresql+psycopg://')):
        return None
    try:
        from app.drift.baseline_store import BaselineStore
        from app.enterprise_store import EnterpriseStore

        return BaselineStore(EnterpriseStore(settings))
    except Exception:
        return None


def capture_scan_drift_baselines_for_tenant(scan: dict, tenant_id: str, settings) -> dict:
    return capture_scan_drift_baselines(
        scan,
        tenant_id=tenant_id,
        baseline_store=_baseline_store_for_settings(settings),
        now=scan.get('timestamp'),
    )
