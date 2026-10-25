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
    if pv <= 0 or cv <= 0:
        raise ValueError("Volumes must be positive decimal strings")
    if pv == cv:
        raise ValueError("Aligned periods require a volume change to compute elasticity")
    with localcontext() as ctx:
        ctx.prec = 28
        cost_ratio = cc / pc if pc > 0 else Decimal(0)
        volume_ratio = cv / pv
        elasticity = cost_ratio / volume_ratio if volume_ratio else Decimal(0)
    result = {
        "cost_change_ratio": format(cost_ratio, "f"),
        "volume_change_ratio": format(volume_ratio, "f"),
        "elasticity_ratio": format(elasticity, "f"),
        "advisory_only": True,
    }
    if elasticity > Decimal("1.15"):
        result["unit_efficiency_regression"] = True
    return result
