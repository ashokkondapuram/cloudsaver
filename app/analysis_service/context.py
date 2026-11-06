"""Unified input contract assembled from ingestion streams A–D (and optional E)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.resource.identity import canonical_resource_id


class ActivityEvent(BaseModel):
    event_id: str
    event_time: str
    event_name: str
    actor_identity: str = ''
    changed_fields: list[str] = Field(default_factory=list)
    is_iac_authorized: bool = False


class CostSnapshot(BaseModel):
    actual_amortized_30d_usd: float | None = None
    actual_unblended_30d_usd: float | None = None
    retail_hourly_rate_usd: float | None = None
    retail_monthly_equivalent_usd: float | None = None
    effective_discount_rate: float | None = None
    cost_source: str | None = None
    daily_cost_spike_pct: float | None = None
    target_sku_retail_monthly_usd: float | None = None


class MetricsSummary(BaseModel):
    cpu_max_pct: float | None = None
    cpu_avg_pct: float | None = None
    cpu_p95_pct: float | None = None
    memory_p95_pct: float | None = None
    network_in_total_gb: float | None = None
    network_out_total_gb: float | None = None
    throttled_requests_count: int | None = None
    burst_credit_balance_min_pct: float | None = None
    error_5xx_rate_pct: float | None = None
    disk_iops_provisioned: float | None = None
    disk_iops_observed_max: float | None = None
    request_count_14d: float | None = None
    backend_target_count: int | None = None
    runtime_hours_30d: float | None = None


class ConfigMetadata(BaseModel):
    encrypted_at_rest: bool | None = None
    publicly_accessible: bool | None = None
    imds_v2_required: bool | None = None
    multi_az_or_ha: bool | None = None
    backup_retention_days: float | None = None
    deletion_protection: bool | None = None
    auto_scaling_enabled: bool | None = None
    disk_state: str | None = None
    power_state: str | None = None
    snapshot_age_days: float | None = None
    snapshot_retention_policy_days: float | None = None
    sensitive_port_exposed_to_internet: bool | None = None
    legacy_sku_generation: bool | None = None
    burstable_sku: bool | None = None
    attached_iam_or_sa: bool | None = None
    zero_traffic_14d: bool | None = None
    ip_associated: bool | None = None
    load_balancer_idle: bool | None = None


class UnifiedResourceContext(BaseModel):
    """Pre-joined resource view for AnalysisService (Streams A–D)."""

    provider: str
    resource_id: str
    resource_type: str
    region: str | None = None
    current_sku: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    config: ConfigMetadata = Field(default_factory=ConfigMetadata)
    metrics: MetricsSummary = Field(default_factory=MetricsSummary)
    cost: CostSnapshot = Field(default_factory=CostSnapshot)
    activity: list[ActivityEvent] = Field(default_factory=list)
    drift_detected: bool = False
    advisor_signals: list[dict[str, Any]] = Field(default_factory=list)
    wiz_issues: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def canonical_id(self) -> str:
        return canonical_resource_id(self.provider, self.resource_id)

    def tag(self, key: str) -> str | None:
        for k, v in self.tags.items():
            if k.lower() == key.lower():
                return v
        return None

    def env_label(self) -> str | None:
        for key in ('env', 'environment', 'stage'):
            value = self.tag(key)
            if value:
                return value.lower()
        return None
