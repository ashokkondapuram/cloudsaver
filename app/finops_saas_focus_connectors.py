"""FOCUS 1.1 SaaS and AI token billing connector stubs (read-only)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any


SUPPORTED = frozenset({"snowflake", "databricks", "mongodb_atlas", "openai", "anthropic"})


def normalize_focus_record(provider: str, row: dict[str, Any]) -> dict[str, Any]:
    if provider not in SUPPORTED:
        raise ValueError("Unsupported SaaS FOCUS provider")
    billed = Decimal(str(row.get("BilledCost") or row.get("billed_cost_usd") or "0"))
    effective = Decimal(str(row.get("EffectiveCost") or row.get("effective_cost_usd") or billed))
    return dict(
        provider_name=provider,
        service_category=str(row.get("ServiceCategory") or row.get("service_category") or "SaaS"),
        service_subcategory=str(row.get("ServiceSubcategory") or row.get("service_subcategory") or ""),
        resource_id=str(row.get("ResourceId") or row.get("resource_id") or ""),
        sku_meter=str(row.get("SkuMeter") or row.get("sku_meter") or ""),
        commitment_discount_status=str(
            row.get("CommitmentDiscountStatus") or row.get("commitment_discount_status") or "Unknown"
        ),
        billed_cost_usd=format(billed, "f"),
        effective_cost_usd=format(effective, "f"),
        charge_period_start=str(row.get("ChargePeriodStart") or row.get("charge_period_start")),
        charge_period_end=str(row.get("ChargePeriodEnd") or row.get("charge_period_end")),
        payload=row,
    )


def connector_capabilities() -> list[dict[str, str]]:
    return [dict(provider=p, mode="read_only", focus_version="1.1") for p in sorted(SUPPORTED)]
