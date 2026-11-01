"""Sixth pillar GreenOps carbon metrics (v3 scaffold)."""
from __future__ import annotations

from decimal import Decimal


def compute_carbon_footprint(
    *,
    energy_kwh: str,
    grid_intensity_gco2_kwh: str,
    embodied_gco2e: str = "0",
) -> dict[str, str]:
    kwh = Decimal(energy_kwh)
    intensity = Decimal(grid_intensity_gco2_kwh)
    embodied = Decimal(embodied_gco2e)
    if kwh < 0 or intensity < 0 or embodied < 0:
        raise ValueError("Carbon inputs must be nonnegative")
    scope2 = kwh * intensity
    return dict(
        energy_kwh=format(kwh, "f"),
        scope2_gco2e=format(scope2, "f"),
        scope3_embodied_gco2e=format(embodied, "f"),
        total_gco2e=format(scope2 + embodied, "f"),
    )


def pillar_assessment(resource: dict, *, catalog_region_intensity: str) -> dict:
    power = resource.get("evidence", {}).get("avg_cpu_watts") or resource.get("avg_cpu_watts")
    if power is None:
        return dict(pillar="greenops", status="unknown", reason="missing_wattage_profile")
    hours = Decimal(str(resource.get("observation_hours") or "730"))
    kwh = (Decimal(str(power)) * hours) / Decimal("1000")
    carbon = compute_carbon_footprint(
        energy_kwh=format(kwh, "f"),
        grid_intensity_gco2_kwh=catalog_region_intensity,
    )
    return dict(pillar="greenops", status="scored", carbon=carbon, advisory_only=True)
