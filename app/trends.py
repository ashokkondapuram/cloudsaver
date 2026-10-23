"""Compare complete scan identities and costs only across equivalent scope/mode."""
from collections import Counter
from datetime import datetime, timedelta, timezone


def calculate_trend(scans, *, days=30, scan_id=None, now=None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    window, times = [], {}
    for scan in scans:
        try:
            observed = datetime.fromisoformat(scan['timestamp'].replace('Z', '+00:00'))
            if scan.get('status') == 'completed' and observed.tzinfo and start <= observed <= now:
                times[scan['scan_id']] = observed
                window.append(scan)
        except (KeyError, ValueError, TypeError):
            continue
    window.sort(key=lambda s: (times[s['scan_id']], s['scan_id']))
    latest = next((s for s in window if s['scan_id'] == scan_id), None) if scan_id else (window[-1] if window else None)
    if not latest:
        return dict(window_days=days, sample_limit=100, total_snapshots=0, direction='unknown',
                    net_change_usd=None, percentage_change=None, new_findings_count=None,
                    resolved_findings_count=None, snapshots=[])
    def group(s):
        return s['mode'], tuple(sorted(s.get('cloud_providers', ['azure']))), s.get('scope_fingerprint')
    # Old snapshots without explicit scope evidence remain viewable but are not compared.
    comparable = [s for s in window[:window.index(latest)+1] if group(s) == group(latest)] if latest.get('scope_fingerprint') else [latest]
    previous = comparable[-2] if len(comparable) >= 2 else None
    def identities(s):
        return {(f.get('cloud_provider', 'azure'), f['rule_id'], f['resource_id'].lower()
                 if f.get('cloud_provider', 'azure') == 'azure' else f['resource_id']) for f in s['findings']}
    amount, prior = latest.get('total_monthly_waste_usd'), previous.get('total_monthly_waste_usd') if previous else None
    delta = round(amount - prior, 2) if amount is not None and prior is not None else None
    direction = 'unknown' if delta is None else ('increasing' if delta > .01 else 'decreasing' if delta < -.01 else 'stable')
    return dict(window_days=days, sample_limit=100, total_snapshots=len(comparable), direction=direction,
        mode=latest['mode'], latest_scan_id=latest['scan_id'], latest_waste_usd=amount, previous_waste_usd=prior,
        net_change_usd=delta, percentage_change=round(delta / prior * 100, 2) if delta is not None and prior and prior > 0 else None,
        new_findings_count=len(identities(latest) - identities(previous)) if previous else None,
        resolved_findings_count=len(identities(previous) - identities(latest)) if previous else None,
        snapshots=[dict(scan_id=s['scan_id'], timestamp=s['timestamp'], total_findings=len(s['findings']),
                        total_monthly_waste_usd=s.get('total_monthly_waste_usd'),
                        findings_by_provider=dict(Counter(f.get('cloud_provider', 'azure') for f in s['findings']))) for s in comparable])
