"""Shared pytest configuration."""

import pytest

from app.analysis_service.platform_rules import reset_platform_evaluators_for_tests


@pytest.fixture(autouse=True)
def _reset_analysis_platform_evaluators():
    """Isolate tests: platform evaluators must not leak between test cases."""
    reset_platform_evaluators_for_tests()
    yield
    reset_platform_evaluators_for_tests()
