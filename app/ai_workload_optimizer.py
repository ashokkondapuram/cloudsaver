"""Model tier routing savings estimator (v2 scaffold; pure math)."""

from decimal import Decimal


def routing_savings_usd(
    requests: int,
    large_cost_per_1k: str,
    small_cost_per_1k: str,
    routable_fraction: str,
) -> dict:
    if requests < 0:
        raise ValueError("requests must be nonnegative")
    large = Decimal(large_cost_per_1k)
    small = Decimal(small_cost_per_1k)
    fraction = Decimal(routable_fraction)
    if not 0 <= fraction <= 1:
        raise ValueError("routable_fraction must be between 0 and 1")
    baseline = (Decimal(requests) / 1000) * large
    optimized = (Decimal(requests) / 1000) * (fraction * small + (1 - fraction) * large)
    savings = max(Decimal(0), baseline - optimized)
    return {
        "baseline_usd": format(baseline, "f"),
        "optimized_usd": format(optimized, "f"),
        "estimated_savings_usd": format(savings, "f"),
        "advisory_only": True,
    }
