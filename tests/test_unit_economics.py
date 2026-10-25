import pytest

from app.unit_economics import compute_elasticity_ratio


def test_elasticity_flags_regression_when_cost_outruns_volume():
    result = compute_elasticity_ratio("100.0000", "150.0000", "100.0000", "110.0000")
    assert result["unit_efficiency_regression"] is True
    assert float(result["elasticity_ratio"]) > 1.15


def test_elasticity_requires_volume_delta():
    with pytest.raises(ValueError):
        compute_elasticity_ratio("10.0000", "12.0000", "5.0000", "5.0000")


def test_elasticity_rejects_nonpositive_volume():
    with pytest.raises(ValueError):
        compute_elasticity_ratio("10.0000", "12.0000", "0.0000", "5.0000")


def test_growth_elasticity_is_not_a_ratio_of_cost_levels():
    result = compute_elasticity_ratio("100", "130", "100", "120")
    assert result["elasticity_ratio"] == "1.5"
    assert result["growth_elasticity_regression"] is True
    assert result.get("unit_efficiency_regression", False) is False


def test_zero_prior_cost_does_not_invent_a_zero_growth_ratio():
    with pytest.raises(ValueError, match="Prior cost"):
        compute_elasticity_ratio("0", "100", "100", "120")


def test_reduced_volume_keeps_unit_cost_deterioration_visible():
    result = compute_elasticity_ratio("100", "95", "100", "80")
    assert result["unit_efficiency_regression"] is True
    assert result["growth_elasticity_regression"] is False
