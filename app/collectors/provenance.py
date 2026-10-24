"""Bounded per-snapshot source ledger; no raw provider errors or credentials."""
from datetime import datetime, timezone
import hashlib
import json


def entry(source_id, collector_type, *, status='available', start=None, end=None, now=None,
          valid_samples=None, expected_samples=None, digest=None, reason=None):
    from app.telemetry_contract import moment
    now = now or datetime.now(timezone.utc)
    stamp = moment(end)
    return dict(source_id=source_id, collector_type=collector_type, status=status,
        observed_window_start=start, observed_window_end=end,
        freshness_seconds=max(0, int((now-stamp).total_seconds())) if stamp else None,
        valid_samples=valid_samples, expected_samples=expected_samples,
        coverage_ratio=valid_samples/expected_samples if expected_samples else None,
        evidence_digest=digest, reason_code=reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def reconciliation(sources, *, conflict=False):
    if conflict:
        return 'source_conflict'
    # Multiple available sources are not proof that state, transition and telemetry agree.
    return 'partial_telemetry'


def compact(inventory, findings, observed_at):
    """Store one full ledger entry per scope/source; observations retain explicit references."""
    from app.telemetry_contract import moment
    fixed_now=moment(observed_at) or datetime.now(timezone.utc)
    ledger={}; conflicts=set()
    for row in inventory:
        provider=row.get('cloud_provider','azure');scope=row.get('scope_id') or row.get('subscription_id')
        if not row.get('data_sources'):
            kind={'azure':'azure_arg','aws':'aws_inventory_api','gcp':'gcp_inventory_api','kubernetes':'prometheus_range_api'}.get(provider,'inventory_api')
            row['data_sources']=[entry(kind,kind,end=observed_at,now=fixed_now)]
            row.setdefault('reconciliation_status','partial_telemetry')
        refs=[]
        for source in row['data_sources']:
            key=(provider,scope,source['source_id'])
            record=dict(source,provider=provider,scope_id=scope)
            if key in ledger and ledger[key]!=record:
                # Conflicting digests for a shared source cannot silently replace one another.
                conflicts.add(key)
                record=dict(record,status='conflict',reason_code='source_manifest_conflict',evidence_digest=None)
            ledger[key]=record
            refs.append({'source_id':source['source_id'],'status':record['status']})
        row['data_sources']=refs
    for row in inventory:
        provider=row.get('cloud_provider','azure');scope=row.get('scope_id') or row.get('subscription_id')
        for ref in row['data_sources']:
            key=(provider,scope,ref['source_id'])
            if key in conflicts:
                row['reconciliation_status']='source_conflict';ref['status']='conflict'
                ledger[key].update(status='conflict',reason_code='source_manifest_conflict',evidence_digest=None)
    by_identity={(r.get('cloud_provider','azure'),r['resource_id']):r for r in inventory}
    for finding in findings:
        row=by_identity.get((finding.get('cloud_provider','azure'),finding['resource_id']))
        if row:
            finding['data_sources']=row['data_sources']
            finding['reconciliation_status']=row.get('reconciliation_status','partial_telemetry')
            if finding['reconciliation_status']=='source_conflict':
                finding['estimated_monthly_waste_usd']=None
                finding['cost_attribution']=None
    return [ledger[key] for key in sorted(ledger)]
