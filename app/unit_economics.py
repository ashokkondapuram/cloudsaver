"""Unit economics elasticity math for aligned billing and volume windows."""

from decimal import Decimal, localcontext

from app.commitment_arbitrage import parse_strict_monetary_decimal


def compute_elasticity_ratio(
    prior_cost: str,
    current_cost: str,
    prior_volume: str,
    current_volume: str,
) -> dict:
    """Cost elasticity vs volume; flags regression when spend outpaces volume."""
    pc = parse_strict_monetary_decimal(prior_cost)
    cc = parse_strict_monetary_decimal(current_cost)
    pv = parse_strict_monetary_decimal(prior_volume)
    cv = parse_strict_monetary_decimal(current_volume)
    if pc <= 0 or pv <= 0 or cv <= 0:
        raise ValueError("Prior cost and both volumes must be positive decimal strings")
    if pv == cv:
        raise ValueError("Aligned periods require a volume change to compute elasticity")
    with localcontext() as ctx:
        ctx.prec = 50
        cost_ratio = cc / pc
        volume_ratio = cv / pv
        cost_growth = (cc - pc) / pc
        volume_growth = (cv - pv) / pv
        elasticity = cost_growth / volume_growth
        unit_cost_ratio = cost_ratio / volume_ratio
    result = {
        "cost_change_ratio": format(cost_ratio, "f"),
        "volume_change_ratio": format(volume_ratio, "f"),
        "elasticity_ratio": format(elasticity, "f"),
        "cost_growth_ratio": format(cost_growth, "f"),
        "volume_growth_ratio": format(volume_growth, "f"),
        "unit_cost_ratio": format(unit_cost_ratio, "f"),
        "growth_elasticity_regression": volume_growth > 0 and elasticity > Decimal("1.15"),
        "advisory_only": True,
    }
    if unit_cost_ratio > Decimal("1.15"):
        result["unit_efficiency_regression"] = True
    return result
