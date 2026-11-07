"""Human-approved commitment ladder planner (v2 scaffold; no purchase APIs)."""

from decimal import Decimal, ROUND_HALF_UP

from app.commitment_arbitrage import calculate_clean_commitment_baseline


def _tranche(ceiling: str, step_pct: str) -> str:
    amount = Decimal(ceiling) * Decimal(step_pct) / Decimal(100)
    return format(amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")


def commitment_ladder(raw_p10_hr: str, waste_hr: str, existing_hr: str, steps: tuple[str, ...] = ("25", "50", "75")) -> list[dict]:
    baseline = calculate_clean_commitment_baseline(raw_p10_hr, waste_hr, existing_hr)
    ceiling = baseline["recommended_new_commitment_hr"]
    out = []
    for i, step in enumerate(steps):
        out.append(
            {
                "step_pct": step,
                "quarter": i + 1,
                "recommended_new_commitment_hr": _tranche(ceiling, step),
                "purchase_authorized": False,
                "status": "scenario_only",
                "ladder_note": "Stagger purchases to avoid simultaneous cliff expirations",
            }
        )
    return out
