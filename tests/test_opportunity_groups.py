from app.pricing import opportunity_totals


def finding(resource, amount, group=None):
    return dict(resource_id=resource, estimated_monthly_waste_usd=amount, opportunity_group_id=group)


def test_overlapping_resource_and_verified_workload_alternatives_are_not_added():
    result = opportunity_totals([finding('vm', 100, 'workload'), finding('disk', 40, 'workload'),
        finding('other', 20), finding('other', 25)])
    assert result['total_monthly_opportunity_usd'] == 125
    assert result['opportunity_group_count'] == 2


def test_unknown_alternative_prevents_a_complete_financial_total():
    result = opportunity_totals([finding('vm', 100, 'workload'), finding('disk', None, 'workload')])
    assert result['total_monthly_opportunity_usd'] is None
    assert result['known_monthly_opportunity_usd'] == 100
    assert result['unpriced_group_count'] == 1


def test_nonfinite_or_boolean_estimates_remain_unknown():
    for value in (float('nan'), float('inf'), True, -1):
        assert opportunity_totals([finding('disk', value)])['total_monthly_opportunity_usd'] is None
