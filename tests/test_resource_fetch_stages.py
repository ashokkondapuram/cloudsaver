from app.resource_fetch_stages import init_fetch_stages, sync_fetch_stages, any_pending


def test_sync_fetch_stages_marks_activity_and_analysis():
    evidence = {}
    init_fetch_stages(evidence)
    evidence['live_sources'] = {'activity_log': 'collected'}
    evidence['state_history'] = [{'state': 'Attached', 'start': '2026-01-01T00:00:00Z', 'end': '2026-01-02T00:00:00Z', 'complete': True}]
    evidence['analysis_readiness'] = {'configuration': 'complete'}
    sync_fetch_stages(evidence, findings=[{'rule_id': 'X', 'retail_estimate_usd': 1.0}])
    assert evidence['fetch_stages']['activity_log'] == 'completed'
    assert evidence['fetch_stages']['analysis'] == 'completed'
    assert evidence['fetch_stages']['retail'] == 'completed'
    assert not any_pending(evidence['fetch_stages'])


def test_costs_stays_pending_without_billing():
    evidence = {}
    init_fetch_stages(evidence)
    sync_fetch_stages(evidence, findings=[])
    assert evidence['fetch_stages']['costs'] == 'pending'
    assert any_pending(evidence['fetch_stages'])
