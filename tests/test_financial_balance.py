from app.financial_balance import resource_financial_balance


def test_billed_vs_retail_and_waste():
    balance = resource_financial_balance(
        billed_cost_usd=15,
        effective_cost_usd=12,
        retail_run_rate_usd=19.71,
        opportunity=dict(total_monthly_opportunity_usd=13.31),
    )
    assert balance['retail_run_rate_usd'] == 19.71
    assert balance['retail_waste_opportunity_usd'] == 13.31
    assert balance['billed_vs_retail_usd'] == -4.71
    assert balance['retail_list_savings_usd'] == 4.71
    assert balance['commitment_benefit_usd'] == 3
    assert balance['modeled_payable_reduction_usd'] == 13.31


def test_waste_without_billing():
    balance = resource_financial_balance(
        billed_cost_usd=None,
        effective_cost_usd=None,
        retail_run_rate_usd=5,
        opportunity=dict(total_monthly_opportunity_usd=2),
    )
    assert balance['modeled_payable_reduction_usd'] == 2
    assert balance['billed_vs_retail_usd'] is None
