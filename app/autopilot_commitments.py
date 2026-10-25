"""Human-approved commitment ladder planner (v2 scaffold; no purchase APIs)."""

from app.commitment_arbitrage import calculate_clean_commitment_baseline


def commitment_ladder(raw_p10_hr: str, waste_hr: str, existing_hr: str, steps: tuple[str, ...] = ("25", "50", "75")) -> list[dict]:
    baseline = calculate_clean_commitment_baseline(raw_p10_hr, waste_hr, existing_hr)
    ceiling = baseline["recommended_new_commitment_hr"]
    return [
        {
            "step_pct": step,
            "recommended_new_commitment_hr": ceiling,
            "purchase_authorized": False,
            "status": "scenario_only",
        }
        for step in steps
    ]
