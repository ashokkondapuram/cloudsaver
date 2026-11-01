"""Model tier routing and Azure OpenAI PTU vs pay-as-you-go break-even math."""

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


def ptu_break_even_tokens_per_min(
    *,
    payg_usd_per_1k_tokens: str,
    ptu_usd_hr: str,
    ptu_tokens_per_min_capacity: str,
) -> dict:
    payg = Decimal(payg_usd_per_1k_tokens)
    ptu_hr = Decimal(ptu_usd_hr)
    capacity = Decimal(ptu_tokens_per_min_capacity)
    if payg <= 0 or ptu_hr <= 0 or capacity <= 0:
        raise ValueError("PTU break-even inputs must be positive")
    payg_per_min = payg * (capacity / Decimal("1000"))
    ptu_per_min = ptu_hr / Decimal("60")
    return dict(
        payg_usd_per_min_at_capacity=format(payg_per_min, "f"),
        ptu_usd_per_min=format(ptu_per_min, "f"),
        ptu_favorable=payg_per_min >= ptu_per_min,
        advisory_only=True,
    )
