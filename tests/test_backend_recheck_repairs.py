from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace


def test_running_refresh_does_not_hide_incomplete_evidence():
    from app.resource_timestamps import observation_row_fields
    result = observation_row_fields({'evidence': {'fetch_stages': {'analysis': 'running'}}})
    assert result['refresh_in_progress']
    assert result['analysis_stale'] and result['evidence_incomplete']


def test_future_analysis_timestamp_is_not_fresh():
    from app.resource_timestamps import analysis_is_stale
    now = datetime.now(timezone.utc)
    assert analysis_is_stale({'last_analyzed_at': (now + timedelta(hours=1)).isoformat()}, now=now)


def test_missing_network_cannot_establish_idle_compute():
    from app.analysis_service.evaluators._helpers import is_idle_compute, is_idle_load_balancer
    metrics = SimpleNamespace(cpu_max_pct=0, network_in_total_gb=None, network_out_total_gb=None,
                              backend_target_count=0, request_count_14d=None)
    ctx = SimpleNamespace(metrics=metrics, config=SimpleNamespace(load_balancer_idle=False))
    assert not is_idle_compute(ctx)
    assert not is_idle_load_balancer(ctx)


def test_waste_is_not_retail_cost():
    from app.azure_json_profile import retail_monthly_from_scan
    store = SimpleNamespace(get=lambda *args: {'findings': [{'resource_id': '/a', 'estimated_monthly_waste_usd': 30}]})
    assert retail_monthly_from_scan(store, {'tenant_id': 't'}, 's', 'azure', '/a')[0] is None


def test_reconciliation_selects_comparable_revision():
    from app.azure_json_profile import finance_reconciled_benefit
    valid = dict(period_start='2026-10-01', period_end='2026-11-01', currency='USD', reconciled_financial_benefit='12.30')
    rows = [(dict(valid, currency='EUR'),), (dict(valid, period_start=None),), (valid,)]
    store = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: rows))
    assert finance_reconciled_benefit(store, 't', 'azure', '/a', observation_start=date(2026,10,1), observation_end=date(2026,11,1)) == 12.3


def test_scope_predicate_denies_empty_grants():
    from app.focus import summary_scope_sql
    assert summary_scope_sql({'allowed_providers': []}) == ('1=0', ())
    sql, args = summary_scope_sql({'allowed_providers': ['aws'], 'aws_accounts': [{'account_id': 'allowed'}]})
    assert 'sub_account IN' in sql
    assert args == ('aws', 'allowed')


def test_remote_code_mode_fails_closed(monkeypatch):
    import pytest
    from app.code_mode_executor import execute_snippet
    monkeypatch.setenv('CLOUDFLARE_CODE_MODE_BRIDGE_URL', 'https://bridge.example')
    monkeypatch.setenv('CLOUDSAVER_CODE_MODE_STUB', 'false')
    with pytest.raises(RuntimeError, match='disabled'):
        execute_snippet(run_id='r', tenant_id='t', snippet='function transform(input) { return input; }', input_value={})


def test_worker_readiness_dependency_cannot_block_liveness():
    from threading import Event
    from time import monotonic
    from workers.health import WorkerHealth
    release = Event()
    calls = []
    def blocked():
        calls.append(True)
        release.wait(5)
    health = WorkerHealth(dependency=blocked, dependency_timeout=0.01)
    health.touch()
    try:
        start = monotonic()
        assert health.status('/health/ready')[0] == 503
        assert health.status('/health/ready')[0] == 503
        assert health.status('/health/live')[0] == 200
        assert monotonic() - start < 0.5
        assert len(calls) == 1
    finally:
        release.set()


def test_empty_account_is_unassessed_instead_of_perfect():
    from app.analysis_service.service import AnalysisService
    result = AnalysisService().analyze_account([])
    assert result.assessment_status == 'unassessed'
    assert result.account_pillar_scores == {}


def test_processor_requires_explicit_opt_in_and_purpose():
    import pytest
    from app.ai_processor_guard import assert_processor_allowed
    for tenant in ({}, {'ai_enabled': True}, {'ai_enabled': True, 'ai_purposes': []}, {'ai_enabled': 'true', 'ai_purposes': ['investigation']}):
        with pytest.raises(PermissionError):
            assert_processor_allowed(tenant, purpose='investigation', payload={})
    assert_processor_allowed({'ai_enabled': True, 'ai_purposes': ['investigation']}, purpose='investigation', payload={})
