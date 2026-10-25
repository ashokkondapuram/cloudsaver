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
