"""Match unused commitments to spot/on-demand node pool drafts (v3 scaffold)."""
from __future__ import annotations

from decimal import Decimal


def arbitrage_node_pool_capacity(
    *,
    unused_commitment_usd_hr: str,
    spot_interruption_score: str,
    on_demand_usd_hr: str,
) -> dict:
    unused = Decimal(unused_commitment_usd_hr)
    spot_risk = Decimal(spot_interruption_score)
    on_demand = Decimal(on_demand_usd_hr)
    if unused < 0 or spot_risk < 0 or on_demand <= 0:
        raise ValueError("Invalid arbitrage inputs")
    prefer_commitment = unused > 0
    prefer_spot = spot_risk <= Decimal("0.15") and not prefer_commitment
    return dict(
        prefer_prepaid_commitment=prefer_commitment,
        prefer_spot=prefer_spot,
        prefer_on_demand=not (prefer_commitment or prefer_spot),
        advisory_only=True,
    )
