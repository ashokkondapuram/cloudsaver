"""Compare Azure retail list prices to imported billing and finding waste."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _money(value) -> float | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            return None
        return float(parsed.quantize(Decimal('0.01')))
    except (InvalidOperation, TypeError, ValueError):
        return None


def resource_financial_balance(
    *,
    billed_cost_usd,
    effective_cost_usd,
    retail_run_rate_usd,
    opportunity,
):
    """Return comparable 30-day / monthly USD measures for one resource.

    - retail_run_rate_usd: Azure catalog list run-rate (from retail meters).
    - retail_waste_opportunity_usd: modeled waste from exact retail components on findings.
    - billed_vs_retail_usd: billed − retail run-rate (positive ⇒ paying above list in-window).
    - retail_list_savings_usd: retail run-rate − billed (positive ⇒ discount vs list).
    - commitment_benefit_usd: billed − effective (positive ⇒ commitment/amortization lowered payable).
    - modeled_payable_reduction_usd: conservative min(billed, waste opportunity) when both known.
    """
    opp = opportunity or {}
    waste = opp.get('total_monthly_opportunity_usd')
    waste_incomplete = False
    if waste is None and opp.get('known_monthly_opportunity_usd') is not None:
        waste = opp.get('known_monthly_opportunity_usd')
        waste_incomplete = True

    billed = _money(billed_cost_usd)
    effective = _money(effective_cost_usd)
    retail = _money(retail_run_rate_usd)
    waste_amount = _money(waste)

    balance = dict(
        retail_run_rate_usd=retail,
        retail_waste_opportunity_usd=waste_amount,
        retail_waste_opportunity_incomplete=waste_incomplete,
        billed_vs_retail_usd=None,
        retail_list_savings_usd=None,
        commitment_benefit_usd=None,
        modeled_payable_reduction_usd=None,
    )

    if billed is not None and retail is not None:
        balance['billed_vs_retail_usd'] = _money(billed - retail)
        balance['retail_list_savings_usd'] = _money(retail - billed)

    if billed is not None and effective is not None:
        balance['commitment_benefit_usd'] = _money(billed - effective)

    if waste_amount is not None:
        if billed is not None:
            balance['modeled_payable_reduction_usd'] = _money(min(billed, waste_amount))
        else:
            balance['modeled_payable_reduction_usd'] = waste_amount

    return balance
