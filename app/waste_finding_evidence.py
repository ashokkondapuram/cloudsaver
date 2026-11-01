"""Normalized evidence persisted on Azure waste_findings rows for downstream analysis."""


def waste_finding_evidence(finding, *, scan_id, mode):
    """Merge scan context with finding evidence without dropping analysis fields."""
    raw = finding.get('evidence') or {}
    evidence = dict(raw) if isinstance(raw, dict) else {}
    evidence['scan_id'] = scan_id
    evidence['mode'] = mode
    for key in ('reconciliation_status', 'data_sources', 'collector_version', 'evidence_schema_version'):
        if finding.get(key) is not None and key not in evidence:
            evidence[key] = finding[key]
    return evidence
