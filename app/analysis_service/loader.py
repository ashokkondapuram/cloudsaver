"""Build UnifiedResourceContext from normalized scan payloads (ingestion output only)."""
from __future__ import annotations

from typing import Any
import math

from app.analysis_service.context import (
    ActivityEvent,
    ConfigMetadata,
    CostSnapshot,
    MetricsSummary,
    UnifiedResourceContext,
)
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series
from datetime import datetime, timezone


def _metric_p95(metrics: dict, key: str, now: datetime) -> float | None:
    raw = metrics.get(key)
    if not isinstance(raw, (list, dict)):
        return None
    result = evaluate_series(raw, TimeSeriesEvidenceContract('metric', 'P95'), now=now, require_resource_age=False)
    if not result.is_sufficient:
        return None
    return float(result.observed_value)


def _metric_max(metrics: dict, key: str, now: datetime) -> float | None:
    raw = metrics.get(key)
    if not isinstance(raw, (list, dict)):
        return None
    result = evaluate_series(raw, TimeSeriesEvidenceContract('metric', 'MAX'), now=now, require_resource_age=False)
    if not result.is_sufficient:
        return None
    return float(result.observed_value)


def _activity_from_history(evidence: dict) -> list[ActivityEvent]:
    events: list[ActivityEvent] = []
    for item in evidence.get('activity_events') or []:
        if isinstance(item, dict) and item.get('event_id'):
            events.append(ActivityEvent.model_validate(item))
    if events:
        return events
    for item in evidence.get('state_history') or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('operation') or item.get('state') or 'state_change')
        events.append(
            ActivityEvent(
                event_id=str(item.get('event_id') or f"state:{name}:{item.get('start')}"),
                event_time=str(item.get('start') or item.get('end') or ''),
                event_name=name,
                actor_identity=str(item.get('actor') or ''),
                is_iac_authorized=bool(item.get('is_iac_authorized')),
            )
        )
    return events


def context_from_inventory_row(row: dict, *, observed_at: str | None = None) -> UnifiedResourceContext:
    """Map a canonical inventory observation into UnifiedResourceContext."""
    evidence = row.get('evidence') or {}
    if not isinstance(evidence, dict):
        evidence = {}
    now = datetime.now(timezone.utc)
    if observed_at:
        try:
            now = datetime.fromisoformat(observed_at.replace('Z', '+00:00')).astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass
    metrics_raw = evidence.get('metrics') if isinstance(evidence.get('metrics'), dict) else {}
    tags = evidence.get('tags') or evidence.get('labels') or {}
    if not isinstance(tags, dict):
        tags = {}

    cost = CostSnapshot(
        actual_amortized_30d_usd=_float(evidence.get('effective_cost_usd') if evidence.get('effective_cost_usd') is not None else evidence.get('amortized_cost_usd')),
        actual_unblended_30d_usd=_float(evidence.get('billed_cost_usd')),
        retail_hourly_rate_usd=_float(evidence.get('retail_hourly_usd')),
        retail_monthly_equivalent_usd=_float(evidence.get('retail_monthly_usd') if evidence.get('retail_monthly_usd') is not None else evidence.get('retail_estimate_usd')),
        effective_discount_rate=_float(evidence.get('effective_discount_rate')),
        cost_source=evidence.get('cost_source'),
        daily_cost_spike_pct=_float(evidence.get('daily_cost_spike_pct')),
        target_sku_retail_monthly_usd=_float(evidence.get('target_sku_retail_monthly_usd')),
    )

    assoc = evidence.get('association_verified')
    ip_associated = evidence.get('ip_associated')
    if ip_associated is None and isinstance(assoc, bool):
        ip_associated = assoc

    imds_raw = evidence.get('imds_v2_required')
    imds_v2_required = imds_raw if isinstance(imds_raw, bool) else None

    config = ConfigMetadata(
        encrypted_at_rest=evidence.get('encrypted') if 'encrypted' in evidence else evidence.get('encrypted_at_rest'),
        publicly_accessible=evidence.get('publicly_accessible'),
        imds_v2_required=imds_v2_required,
        multi_az_or_ha=evidence.get('multi_az'),
        backup_retention_days=_float(evidence.get('backup_retention_days')),
        deletion_protection=evidence.get('deletion_protection'),
        auto_scaling_enabled=evidence.get('auto_scaling_enabled'),
        disk_state=evidence.get('disk_state'),
        power_state=evidence.get('power_state'),
        snapshot_age_days=_float(evidence.get('snapshot_age_days')),
        snapshot_retention_policy_days=_float(evidence.get('snapshot_retention_policy_days')),
        sensitive_port_exposed_to_internet=evidence.get('sensitive_port_exposed'),
        legacy_sku_generation=evidence.get('legacy_sku_generation'),
        burstable_sku=evidence.get('burstable_sku'),
        attached_iam_or_sa=evidence.get('attached_iam_or_sa'),
        zero_traffic_14d=evidence.get('zero_traffic_14d'),
        ip_associated=ip_associated if isinstance(ip_associated, bool) else None,
        load_balancer_idle=evidence.get('load_balancer_idle') if isinstance(evidence.get('load_balancer_idle'), bool) else None,
    )

    metrics = MetricsSummary(
        cpu_max_pct=_metric_max(metrics_raw, 'cpu_percent', now),
        cpu_p95_pct=_metric_p95(metrics_raw, 'cpu_percent', now),
        memory_p95_pct=_metric_p95(metrics_raw, 'memory_percent', now),
        network_in_total_gb=_float(evidence.get('network_in_total_gb')),
        network_out_total_gb=_float(evidence.get('network_out_total_gb')),
        throttled_requests_count=_int(evidence.get('throttled_requests_count')),
        burst_credit_balance_min_pct=_float(evidence.get('burst_credit_balance_min_pct')),
        error_5xx_rate_pct=_float(evidence.get('error_5xx_rate_pct')),
        disk_iops_provisioned=_float(evidence.get('provisioned_iops') or evidence.get('provisionedIops')),
        disk_iops_observed_max=_metric_max(metrics_raw, 'iops', now),
        request_count_14d=_float(evidence.get('request_count_14d')),
        backend_target_count=_int(evidence.get('backend_target_count') or evidence.get('hosted_app_count')),
        runtime_hours_30d=_float(evidence.get('runtime_hours_30d')),
    )

    sku = evidence.get('vm_size') or evidence.get('sku_name') or evidence.get('skuName')
    return UnifiedResourceContext(
        provider=row.get('cloud_provider') or row.get('provider') or 'azure',
        resource_id=row['resource_id'],
        resource_type=row.get('resource_type') or '',
        region=row.get('region'),
        current_sku=str(sku) if sku else None,
        tags={str(k): str(v) for k, v in tags.items()},
        config=config,
        metrics=metrics,
        cost=cost,
        activity=_activity_from_history(evidence),
        drift_detected=bool(evidence.get('drift_detected')),
        advisor_signals=list(evidence.get('advisor_signals') or []),
        wiz_issues=list(evidence.get('wiz_issues') or []),
    )


def contexts_from_scan(scan: dict) -> list[UnifiedResourceContext]:
    observed_at = scan.get('timestamp') or scan.get('observed_at')
    inventory = scan.get('inventory') or []
    return [context_from_inventory_row(row, observed_at=observed_at) for row in inventory if isinstance(row, dict) and row.get('resource_id')]


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
        if not math.isfinite(out):
            return None
        return out
    except (TypeError, ValueError, OverflowError):
        return None


def _int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None
