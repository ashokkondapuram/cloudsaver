import os

import pytest

from app.collectors import billing_sync


def test_azure_cost_pacing_development_has_no_spacing(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT', 'development')
    monkeypatch.setenv('CLOUDSAVER_AZURE_COST_INTERVAL_SECONDS', '45')
    interval, deadline = billing_sync._azure_cost_pacing()
    assert interval == 0.0
    assert deadline >= 120


def test_azure_cost_pacing_production_respects_interval(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT', 'production')
    monkeypatch.setenv('CLOUDSAVER_AZURE_COST_INTERVAL_SECONDS', '20')
    interval, deadline = billing_sync._azure_cost_pacing()
    assert interval == 20.0
    assert deadline >= interval + 90
