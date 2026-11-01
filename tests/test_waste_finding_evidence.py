from app.waste_finding_evidence import waste_finding_evidence


def test_waste_finding_evidence_merges_scan_context_and_finding_fields():
    finding = dict(
        resource_id='/x',
        evidence={'encrypted': True},
        reconciliation_status='partial_telemetry',
        data_sources=[{'source_id': 'inventory'}],
    )
    payload = waste_finding_evidence(finding, scan_id='scan-1', mode='azure')
    assert payload['mode'] == 'azure' and payload['scan_id'] == 'scan-1'
    assert payload['encrypted'] is True
    assert payload['reconciliation_status'] == 'partial_telemetry'
    assert payload['data_sources'] == [{'source_id': 'inventory'}]
