"""scanner_pipeline finalize step."""

from app.scanner_pipeline import finalize_scan_payload


def test_finalize_scan_payload_watermark_and_pillar(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_CLOUD_ADVISOR_ENABLED', 'false')
    calls = []

    def fake_attach(scan):
        calls.append('pillar')

    def fake_capture(scan, tenant_id, settings):
        calls.append('drift')

    monkeypatch.setattr(
        'app.analysis_service.pipeline.attach_pillar_analysis',
        fake_attach,
    )
    monkeypatch.setattr(
        'app.drift.scan_baselines.capture_scan_drift_baselines_for_tenant',
        fake_capture,
    )
    scan = {
        'inventory': [
            {
                'scope_id': 's1',
                'subscription_id': 's1',
                'evidence': {'activity_events': [{'event_time': '2026-04-01T12:00:00Z'}]},
            }
        ],
    }
    finalize_scan_payload(scan, tenant_id='t1', settings=None, previous_completed_scan=None)
    assert 'activity_ingestion_watermark' in scan['inventory'][0]['evidence']
    assert calls == ['pillar', 'drift']
