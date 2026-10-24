"""Only trusted audit, complete scope and reconciled net billing can establish realized savings."""
from datetime import datetime,timezone,date,time
from decimal import Decimal
from app.commitment_arbitrage import parse_strict_monetary_decimal as money,decimal_text
from app.telemetry_contract import moment

STATES=('reviewed','accepted_for_investigation','scheduled','rejected','deferred','verified_completed','reopened_on_regression')
TRANSITIONS={
    'reviewed':{'accepted_for_investigation','rejected','deferred'},
    'accepted_for_investigation':{'scheduled','rejected','deferred'},
    'scheduled':{'rejected','deferred'},
    'rejected':{'reviewed'},'deferred':{'reviewed','accepted_for_investigation','rejected'},
    'verified_completed':set(),'reopened_on_regression':{'accepted_for_investigation','deferred','rejected'},
}


def scope_is_complete(case,scan):
    if scan.get('status')!='completed' or scan.get('data_origin')=='legacy_synthetic':return False
    coverage=scan.get('coverage_manifest') or {}
    if coverage.get('partial') is True or coverage.get('failed_scopes'):return False
    return any(r.get('provider')==case['provider'] and r.get('scope_id')==case['scope_id'] and r.get('status')=='completed'
               and r.get('supported_inventory_complete') is True and case.get('resource_type','').lower() in [t.lower() for t in r.get('supported_resource_types',[])]
               and (case['provider']!='aws' or case.get('region') in (r.get('regions') or []))
               and (case['provider']!='gcp' or not case.get('resource_type','').startswith('compute.googleapis.com/') or case.get('region') in (r.get('regions') or []))
               for r in scan.get('scope_results',[]))


def evaluate_realized_savings(case,scan,*,audit=None,billing=None,slo=None,now=None):
    now=now or datetime.now(timezone.utc)
    result=dict(state=case['state'],status='insufficient_evidence',verified_realized_savings_usd=None,reasons=[],automatic_execution=False)
    historical=case.get('last_verified_result') or {}
    result.update(verified_period_start=historical.get('verified_period_start'),verified_period_end=historical.get('verified_period_end'))
    def insufficient(reason):return dict(result,reasons=[reason])
    if not scope_is_complete(case,scan):return insufficient('unverified_scope_missing')
    observed=moment(scan.get('timestamp'));scheduled=moment(case.get('scheduled_at'))
    if not observed or not 0<=(now-observed).total_seconds()<86400:return insufficient('latest_scope_observation_is_stale')
    if not scheduled or observed<=scheduled:return insufficient('post_change_observation_required')
    normalize=lambda rid:rid.lower() if case['provider']=='azure' else rid
    current=next((r for r in scan.get('inventory',[]) if r.get('cloud_provider','azure')==case['provider'] and normalize(r['resource_id'])==normalize(case['resource_id'])),None)
    # A fresh observation may be a new incarnation of the same resource; recurrence still requires review.
    recurrence=any(f.get('cloud_provider','azure')==case['provider'] and normalize(f['resource_id'])==normalize(case['resource_id']) and f['rule_id'] in case.get('baseline_rule_ids',[]) for f in scan.get('findings',[]))
    evidence=(current or {}).get('evidence') or {};metrics=evidence.get('metrics') or {}
    post_change=moment(evidence.get('regression_window_start'))
    regression=bool(post_change and post_change>=scheduled and
        ((type(evidence.get('oom_kill_count_30d')) is int and evidence['oom_kill_count_30d']>0)
         or (type(evidence.get('p95_cfs_throttled_ratio')) in (int,float) and evidence['p95_cfs_throttled_ratio']>.05)))
    # Existing validated summaries can also establish a post-action regression window.
    for name,threshold in (('oom',0),('throttling',.05)):
        metric=metrics.get(name) or {};start=moment(metric.get('window_start'));end=moment(metric.get('window_end'))
        value=metric.get('maximum' if name=='oom' else 'p95')
        if metric.get('sufficient') is True and start and start>=scheduled and end and end<=observed and 0<=(observed-end).total_seconds()<86400 and type(value) in (int,float) and value>threshold:
            regression=True
    if case['state']=='verified_completed':
        if recurrence or regression or case.get('action')=='retirement' and current is not None:
            return dict(result,state='reopened_on_regression',status='regression_detected',verified_realized_savings_usd='0.0000',reasons=['waste_or_reliability_regression'])
        return dict(result,status='no_regression_observed',verified_realized_savings_usd=case.get('previous_verified_savings'),reasons=[])
    if case['state']!='scheduled':return insufficient('case_must_be_scheduled_before_verification')
    if case.get('action')=='retirement' and current is not None:return insufficient('resource_still_present')
    if case.get('action')=='rightsizing' and current is None:return insufficient('rightsized_resource_is_missing')
    if not audit or audit.get('trusted') is not True:return insufficient('authoritative_action_event_required')
    event=moment(audit.get('occurred_at'))
    operation='delete' if case.get('action')=='retirement' else 'resize'
    if audit.get('operation')!=operation or audit.get('status')!='Succeeded' or not event or not scheduled<=event<=observed:
        return insufficient('audit_event_does_not_match_the_action_window')
    if not billing or billing.get('trusted') is not True or billing.get('provider_reconciled') is not True or billing.get('coverage_complete') is not True or billing.get('overhead_inventory_complete') is not True:
        return insufficient('reconciled_billing_and_complete_replacement_overhead_required')
    if case.get('action')=='rightsizing':
        gate=(slo or {}).get('gate') or {};start=moment(gate.get('observation_window_start'));end=moment(gate.get('observation_window_end'))
        if recurrence or regression:return insufficient('post_change_waste_or_reliability_regression')
        if not slo or slo.get('trusted') is not True or gate.get('status')!='review_eligible' or not start or start<event or not end or not 0<=(observed-end).total_seconds()<86400:
            return insufficient('complete_post_change_slo_window_required')
        if billing.get('workload_normalized') is not True or not billing.get('normalization_method'):
            return insufficient('workload_normalized_billing_required')
    try:
        before_a,before_b,after_a,after_b=(date.fromisoformat(billing[k]) for k in ('baseline_start','baseline_end','observation_start','observation_end'))
        if (before_b-before_a).days!=30 or (after_b-after_a).days!=30 or datetime.combine(before_b,time.min,timezone.utc)>scheduled or datetime.combine(after_a,time.min,timezone.utc)<event or after_b>observed.date():
            return insufficient('comparable_closed_30_day_billing_windows_required')
        baseline,post,overhead,transition=map(money,(billing['baseline_monthly_cost_usd'],billing['post_resource_cost_usd'],billing['new_backup_or_snapshot_overhead_usd'],billing['one_time_transition_cost_usd']))
        if billing.get('currency')!='USD':return insufficient('billing_currency_mismatch')
    except (KeyError,TypeError,ValueError):return insufficient('invalid_billing_evidence')
    net=baseline-post-overhead-transition
    return dict(result,state='verified_completed',status='verified_by_trusted_receipts',verified_realized_savings_usd=decimal_text(net),
        verified_period_start=billing['observation_start'],verified_period_end=billing['observation_end'],
        baseline_monthly_cost_usd=decimal_text(baseline),post_resource_cost_usd=decimal_text(post),new_backup_or_snapshot_overhead_usd=decimal_text(overhead),reasons=[],
        one_time_transition_cost_usd=decimal_text(transition),
        warning='Verification trusts the configured collectors’ audit and provider-reconciled billing attestations. It is not independent invoice reconciliation by this service.')
