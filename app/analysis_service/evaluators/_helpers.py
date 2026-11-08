"""Shared helpers for pillar evaluators (pure functions, no I/O)."""
from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.finding import FinancialImpact


def monthly_cost(ctx: UnifiedResourceContext) -> float | None:
    if ctx.cost.actual_amortized_30d_usd is not None:
        return ctx.cost.actual_amortized_30d_usd
    if ctx.cost.retail_monthly_equivalent_usd is not None:
        return ctx.cost.retail_monthly_equivalent_usd
    if ctx.cost.retail_hourly_rate_usd is not None:
        return ctx.cost.retail_hourly_rate_usd * 730.0
    return None


def financial(current: float | None, *, savings: float | None = None, projected: float | None = None) -> FinancialImpact:
    return FinancialImpact(
        current_monthly_cost_usd=current,
        projected_monthly_cost_usd=projected,
        estimated_monthly_savings_usd=savings,
    )


def discount_rate(ctx: UnifiedResourceContext) -> float:
    if ctx.cost.effective_discount_rate is not None:
        return max(0.0, min(1.0, ctx.cost.effective_discount_rate))
    retail = ctx.cost.retail_monthly_equivalent_usd
    actual = ctx.cost.actual_amortized_30d_usd
    if retail and retail > 0 and actual is not None:
        return max(0.0, min(1.0, 1.0 - (actual / retail)))
    return 0.0


def is_orphan_disk(ctx: UnifiedResourceContext) -> bool:
    state = (ctx.config.disk_state or '').lower()
    return state in ('unattached', 'available', 'unassociated')


def is_orphan_public_ip(ctx: UnifiedResourceContext) -> bool:
    rtype = ctx.resource_type.lower()
    if 'publicip' in rtype or 'elastic-ip' in rtype or '/addresses' in rtype:
        return ctx.config.ip_associated is False
    return False


def is_idle_load_balancer(ctx: UnifiedResourceContext) -> bool:
    if ctx.config.load_balancer_idle:
        return True
    targets = ctx.metrics.backend_target_count
    requests = ctx.metrics.request_count_14d
    if targets is not None and targets == 0:
        return requests is not None and requests <= 0
    return False


def is_idle_compute(ctx: UnifiedResourceContext) -> bool:
    m = ctx.metrics
    if m.cpu_max_pct is None:
        return False
    if m.network_in_total_gb is None or m.network_out_total_gb is None:
        return False
    net = m.network_in_total_gb + m.network_out_total_gb
    return m.cpu_max_pct < 5.0 and net < 0.1


def is_rightsizing_candidate(ctx: UnifiedResourceContext) -> bool:
    m = ctx.metrics
    if m.cpu_p95_pct is None or m.memory_p95_pct is None:
        return False
    return m.cpu_p95_pct < 20.0 and m.memory_p95_pct < 30.0


def human_drift_events(ctx: UnifiedResourceContext) -> list:
    return [e for e in ctx.activity if not e.is_iac_authorized]
