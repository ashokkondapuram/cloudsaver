"""Five-pillar review from saved observations. Missing evidence never means safe."""
import hashlib
import json
import re
from decimal import Decimal
from datetime import datetime, timezone

from app.assessment_policy import MODEL_BASE_CODES, POLICY_VERSION, freshness, number, service_checks, timestamp, utilization

PILLARS = ('cost', 'reliability', 'performance', 'security', 'operations')


def resource_key(finding):
    resource = finding['resource_id']
    if finding.get('cloud_provider', 'azure') == 'azure':
        resource = resource.lower()
    return hashlib.sha256((finding.get('cloud_provider', 'azure') + '|' + resource + '|' + finding['rule_id']).encode()).hexdigest()


def category(finding):
    from app.resource_catalog import family
    defined=family(finding)
    if defined:return defined[2]
    kind = finding.get('resource_type', '').lower()
    if kind.endswith(('/persistentvolumeclaim','/persistentvolume','/storageclass')):
        return 'storage'
    if kind.endswith(('/service','/endpointslice')) and finding.get('cloud_provider')=='kubernetes':
        return 'network'
    if finding.get('cloud_provider')=='kubernetes' and kind.startswith('kubernetes.io/'):
        return 'compute'
    if any(x in kind for x in ('disk', 'volume', 'storage')):
        return 'storage'
    if any(x in kind for x in ('rds', 'sql', 'database', 'alloydb', 'aurora')):
        return 'database'
    if any(x in kind for x in ('serverfarm', 'appservice', 'containerapp', 'lambda', 'cloudrun')):
        return 'application'
    if any(x in kind for x in ('network', 'address', 'elastic-ip', 'gateway', 'publicip')):
        return 'network'
    if any(x in kind for x in ('virtualmachine', 'instance', 'container', 'pod', 'cpu', 'memory')):
        return 'compute'
    return 'other'


def tags_of(finding):
    evidence = finding.get('evidence') or {}
    value = evidence.get('tags') or evidence.get('labels') or {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(value, dict) else {}


def protection(finding):
    def normalize(value):
        return re.sub(r'[^a-z0-9]', '', value.casefold())
    tags = {normalize(k): normalize(v) for k, v in tags_of(finding).items()}
    reasons = []
    if finding.get('reconciliation_status')=='source_conflict':
        reasons.append('SOURCE_CONFLICT')
    if any(tags.get(k) in ('true', 'yes', '1', 'enabled') for k in ('donottouch', 'donotdelete', 'retain', 'legalhold')):
        reasons.append('EXPLICIT_RETENTION')
    if any(tags.get(k) in ('drstandby', 'disasterrecoverystandby', 'activestandby', 'coldspare', 'witness', 'donottouch') for k in ('role', 'disasterrecovery', 'purpose')):
        reasons.append('RECOVERY_OR_WITNESS_ROLE')
    if (finding.get('evidence') or {}).get('deletion_protection') is True:
        reasons.append('DELETION_PROTECTION')
    if tags.get('retention') in ('permanent', 'legalhold') or tags.get('migrationwindow') == 'active':
        reasons.append('RETENTION_OR_MIGRATION_HOLD')
    evidence = finding.get('evidence') or {}
    locks = evidence.get('management_locks')
    if isinstance(locks, list) and any(lock in ('CanNotDelete', 'ReadOnly') for lock in locks if isinstance(lock, str)):
        reasons.append('MANAGEMENT_LOCK')
    if evidence.get('backup_enrolled') is True or evidence.get('replication_enrolled') is True:
        reasons.append('BACKUP_OR_REPLICATION')
    return sorted(reasons)


def assess(finding, *, observed_at=None, now=None):
    evidence = finding.get('evidence') or {}
    kind = category(finding)
    protected = protection(finding)
    checks = []

    def check(pillar, code, state, message, fields=None):
        default_fields = {
            'RETAIL_ESTIMATE': ['estimated_monthly_waste_usd'], 'BILLED_COST': ['billing_records'],
            'RECOVERY_SNAPSHOT': ['recent_snapshot_verified'], 'FAILOVER_TOPOLOGY': ['multi_az'],
            'DATABASE_RECOVERY': ['backup_retention_days'], 'ENCRYPTION_AT_REST': ['encrypted'],
            'PUBLIC_DATABASE': ['publicly_accessible'], 'OWNERSHIP': ['tags', 'labels'],
            'DEPENDENCY_GRAPH': ['verified_dependencies'], 'PROTECTED_INTENT': ['tags', 'labels', 'deletion_protection'],
            'UTILIZATION_WINDOW': ['p95_usage', 'minimum_request', 'window_days', 'window_start', 'window_end', 'samples', 'step_seconds', 'dimension', 'unit', 'percentile_method'],
        }
        checks.append(dict(pillar=pillar, code=code, status=state, explanation=message, evidence_fields=fields if fields is not None else default_fields.get(code, [])))

    amount = number(finding.get('estimated_monthly_waste_usd'))
    check('cost', 'RETAIL_ESTIMATE', 'observed' if amount is not None else 'unknown',
          'A saved retail estimate is available; billed spend and realizable savings are unverified.' if amount is not None else 'No verified retail estimate is attached.')
    billed, effective = number(evidence.get('billed_cost_usd')), number(evidence.get('effective_cost_usd'))
    locked = evidence.get('commitment_locked') is True
    check('cost', 'BILLED_COST', 'risk' if locked else 'observed' if billed is not None else 'unknown',
          'Imported charges indicate commitment coverage; verify reallocation before a change.' if locked else
          f'Imported 30-day USD charges: billed {billed:.2f}; effective {effective:.2f}. Coverage must be reviewed.' if billed is not None and effective is not None else
          'Resource-period USD billing evidence is unavailable.', ['billed_cost_usd','effective_cost_usd','billing_coverage','commitment_locked'])
    if kind == 'storage':
        backup = evidence.get('recent_snapshot_verified')
        check('reliability', 'RECOVERY_SNAPSHOT', 'observed' if backup is True else 'risk' if backup is False else 'unknown',
              'Snapshot evidence is present; restore acceptance still requires independent review.' if backup is True else 'A recovery snapshot is absent or its freshness is unverified.')
    else:
        multi_az = evidence.get('multi_az')
        check('reliability', 'FAILOVER_TOPOLOGY', 'observed' if multi_az is True else 'risk' if multi_az is False else 'unknown',
              'Multi-zone configuration is observed; failover has not been tested.' if multi_az is True else 'Redundancy and failover acceptance need review.')
    retention = number(evidence.get('backup_retention_days'))
    if kind == 'database':
        check('reliability', 'DATABASE_RECOVERY', 'unknown' if retention is None else 'risk' if retention < 2 else 'observed',
              'Backup retention is unknown.' if retention is None else f'Observed backup retention: {retention:g} days; production recovery objectives need review.')
    complete_utilization = utilization(evidence, observed_at)
    check('performance', 'UTILIZATION_WINDOW', 'observed' if complete_utilization else 'unknown',
          'Saved 14-day hourly P95 evidence has a complete collector summary; peaks and SLOs still need review.' if complete_utilization else 'Complete utilization/headroom evidence is unavailable; do not infer idle duration from stopped state.')
    if finding.get('cloud_provider')=='kubernetes' and finding.get('resource_type','').startswith('kubernetes.io/') and isinstance(evidence.get('metrics'),dict):
        from app.telemetry_contract import moment
        metrics=evidence.get('metrics') or {}
        def metric(name):
            value=metrics.get(name) or {}
            if not isinstance(value,dict):return None
            end=moment(value.get('window_end'))
            return value if value.get('sufficient') is True and end and 0 <= ((now or datetime.now(timezone.utc))-end).total_seconds() < 86400 else None
        cpu,memory,throttle,oom,restarts=(metric(key) for key in ('cpu','memory','throttling','oom','restarts'))
        check('performance','K8S_FIVE_MINUTE_TELEMETRY','observed' if cpu and memory else 'unknown',
              'CPU rate and memory working-set evidence use validated 30-day five-minute windows.' if cpu and memory else 'Complete five-minute CPU and memory evidence is unavailable.',['metrics.cpu','metrics.memory'])
        check('performance','K8S_CPU_THROTTLING','unknown' if not throttle else 'risk' if throttle['p95']>.02 else 'observed',
              'CPU throttling above 2% blocks request reduction.' if throttle and throttle['p95']>.02 else 'Throttling requires measured five-minute evidence.',['metrics.throttling'])
        oom_risk=oom and oom['maximum']>0
        zero_verified=oom and restarts and oom['maximum']==0 and restarts['maximum']==restarts['minimum']
        check('reliability','K8S_OOM_HISTORY','risk' if oom_risk else 'observed' if zero_verified else 'unknown',
              'OOMKill evidence blocks memory reduction.' if oom_risk else 'A last termination reason alone does not prove a full zero-OOM history.',['metrics.oom','metrics.restarts'])
        check('operations','K8S_SOURCE_RECONCILIATION','risk' if finding.get('reconciliation_status')=='source_conflict' else 'unknown',
              'Conflicting sources require reconciliation.' if finding.get('reconciliation_status')=='source_conflict' else 'Complete cross-source state and transition agreement is unverified.',['reconciliation_status'])
    if kind in ('storage', 'database'):
        encrypted = evidence.get('encrypted')
        check('security', 'ENCRYPTION_AT_REST', 'observed' if encrypted is True else 'risk' if encrypted is False else 'unknown',
              'Encryption is reported enabled.' if encrypted is True else 'Encryption is explicitly disabled.' if encrypted is False else 'Encryption evidence is unavailable.')
    else:
        if kind == 'compute':
            ingress, identity = evidence.get('public_admin_ingress'), evidence.get('imds_v2_required')
            safe = False if ingress is True or identity is False else True if ingress is False and identity is True else None
        elif kind == 'network':
            ingress, waf = evidence.get('unrestricted_ingress'), evidence.get('ddos_or_waf_enabled')
            safe = False if ingress is True else True if ingress is False and waf is True else None
        elif kind == 'application':
            https = evidence.get('https_only')
            safe = https if type(https) is bool else None
        else:
            safe = None
        check('security', 'ACCESS_AND_EXPOSURE', 'unknown' if safe is None else 'observed' if safe else 'risk',
              'Observed access controls support this specific check; other access paths require separate evidence.' if safe else
              'An explicit exposure or identity control requires review.' if safe is False else 'Complete service-specific access evidence is unavailable.',
              ['public_admin_ingress','imds_v2_required','unrestricted_ingress','ddos_or_waf_enabled','https_only'])
    public = evidence.get('publicly_accessible')
    if kind == 'database':
        check('security', 'PUBLIC_DATABASE', 'risk' if public is True else 'observed' if public is False else 'unknown',
              'Database public accessibility is enabled.' if public is True else 'Database public accessibility is disabled.' if public is False else 'Database exposure evidence is unavailable.')
    service_checks(kind, evidence, check)
    from app.pillar_checks import checks as concrete_checks
    # Existing codes remain stable; combine duplicate checks conservatively below.
    concrete_checks(kind,evidence,check,observed_at=observed_at,now=now,protected=protected)
    if complete_utilization:
        ratio = evidence['p95_usage'] / evidence['minimum_request']
        check('performance', 'REQUEST_HEADROOM', 'risk' if ratio > 1 else 'observed',
              f'Saved P95/request ratio: {ratio:.3g}. This is request-sizing evidence, not a memory limit or safety guarantee.',
              ['p95_usage', 'minimum_request'])
    tags = tags_of(finding)
    owner = any(k.casefold() in ('owner', 'owneremail', 'application', 'applicationid') and v.strip() for k, v in tags.items())
    check('operations', 'OWNERSHIP', 'observed' if owner else 'unknown', 'An ownership tag is present; ownership has not been independently verified.' if owner else 'No ownership tag was supplied in this observation.')
    deps = evidence.get('verified_dependencies')
    history = evidence.get('state_history')
    valid_history = False
    if isinstance(history, list) and history and all(isinstance(i, dict) for i in history):
        intervals = [(timestamp(i.get('start')), timestamp(i.get('end')), i.get('complete')) for i in history]
        current = timestamp(now) or datetime.now(timezone.utc)
        valid_history = all(a and b and a < b and complete is True for a,b,complete in intervals)
        valid_history = valid_history and all(a[1] == b[0] for a,b in zip(intervals, intervals[1:])) and 0 <= (current-intervals[-1][1]).total_seconds() < 86400
    valid_deps = isinstance(deps, list) and all(isinstance(d, str) and d for d in deps)
    state = 'risk' if valid_deps and deps else 'observed' if valid_deps and valid_history and evidence.get('dependency_inventory_complete') is True else 'unknown'
    check('operations', 'DEPENDENCY_GRAPH', state,
          f'{len(deps)} active association(s) observed; inspect before modification.' if state == 'risk' else
          'Complete associations and fresh continuous history establish no observed attachments; this is not change approval.' if state == 'observed' else
          'Complete dependency coverage and state history are required. Missing edges are not proof of zero blast radius.')
    if protected:
        check('reliability', 'PROTECTED_INTENT', 'risk', 'Explicit recovery, witness, retention or deletion-protection intent suppresses destructive recommendations.')
    pillars = []
    for pillar in PILLARS:
        items = [c for c in checks if c['pillar'] == pillar]
        state = 'risk' if any(c['status'] == 'risk' for c in items) else 'unknown' if any(c['status'] == 'unknown' for c in items) else 'observed'
        pillars.append(dict(pillar=pillar, status=state, checks=items))
    guardrails = ['VERIFY_CURRENT_STATE', 'REVIEW_DEPENDENCIES', 'CONFIRM_OWNER_AND_RETENTION', 'INDEPENDENT_CHANGE_APPROVAL']
    if kind == 'storage':
        guardrails += ['CREATE_PRE_DELETION_SNAPSHOT', 'VERIFY_RESTORE_AND_RETENTION']
    observation = freshness(observed_at, now)
    if observation['status'] != 'recent':
        guardrails.append('REFRESH_OBSERVATION')
    if protected:
        guardrails.append('NO_DESTRUCTIVE_RECOMMENDATION')
    risk_codes = [c['code'] for c in checks if c['status'] == 'risk']
    gaps = [c['code'] for c in checks if c['status'] == 'unknown']
    priority = 'critical' if any(c in risk_codes for c in ('PUBLIC_DATABASE', 'ENCRYPTION_AT_REST', 'ADMIN_INGRESS', 'SNAPSHOT_EXPOSURE')) else 'high' if risk_codes else 'evidence_required'
    result = dict(resource_key=resource_key(finding), service_category=kind,scope_id=finding.get('scope_id') or finding.get('subscription_id'),opportunity_group_id=finding.get('opportunity_group_id'),
                policy_version=POLICY_VERSION, observation=observation,
                review_priority=priority, risk_check_codes=risk_codes, evidence_gap_codes=gaps,
                disposition='protected' if protected else 'requires_review', protected_reasons=protected,
                risk_level='high' if any(c['status']=='risk' and c['code']!='OBSERVATION_FRESHNESS' for c in checks) else 'unknown',
                automatic_execution=False, pillars=pillars, guardrails=guardrails,
                evidence_coverage=dict(observed=sum(c['status'] != 'unknown' for c in checks), total=len(checks)),
                retail_estimate_usd=amount, billed_cost_usd=billed, effective_cost_usd=effective, commitment_locked=locked, realizable_savings_usd=None)
    # The digest covers only evaluated evidence and policy, never free text or raw identities.
    result['evidence_digest'] = hashlib.sha256(json.dumps(dict(context=ai_context(finding, result), retail_estimate_usd=amount), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def summarize(scan, *, now=None):
    groups, queue = {}, []
    ranks = {'critical': 0, 'high': 1, 'evidence_required': 2}
    now = now if now is not None else datetime.now(timezone.utc)
    for finding in scan['findings']:
        provider = finding.get('cloud_provider', 'azure')
        key = (provider, category(finding))
        group = groups.setdefault(key, dict(provider=provider, service_category=key[1], findings=0, priced_findings=0,
                                            known_retail_subtotal_usd=Decimal(0), protected_findings=0, risk_findings=0,_findings=[]))
        result = assess(finding, observed_at=scan.get('timestamp'), now=now)
        queue.append(dict(resource_id=finding['resource_id'], rule_id=finding['rule_id'], **{k: result[k] for k in ('resource_key', 'service_category', 'review_priority', 'disposition', 'risk_check_codes', 'evidence_gap_codes', 'evidence_digest')}))
        queue.sort(key=lambda item: (ranks[item['review_priority']], item['resource_key']))
        del queue[50:]
        group['_findings'].append(finding)
        group['findings'] += 1
        group['protected_findings'] += bool(result['protected_reasons'])
        group['risk_findings'] += result['risk_level'] == 'high'
        if result['retail_estimate_usd'] is not None:
            group['priced_findings'] += 1
            group['known_retail_subtotal_usd'] += Decimal(str(result['retail_estimate_usd']))
    rows = []
    for group in groups.values():
        group['unknown_price_findings'] = group['findings'] - group['priced_findings']
        from app.pricing import opportunity_totals
        group['known_retail_subtotal_usd']=opportunity_totals(group.pop('_findings'))['known_monthly_opportunity_usd'] if group['priced_findings'] else None
        group.pop('_findings',None)
        rows.append(group)
    finding_count = len(scan['findings'])
    unique_resources = len({resource_key(f) for f in scan['findings']})
    return dict(policy_version=POLICY_VERSION, observation=freshness(scan.get('timestamp'), now),
                review_queue=queue[:50], review_queue_total=finding_count, review_queue_limit=50,
                scan_id=scan['scan_id'], source='saved_finding_observations', full_inventory=False,
                coverage={'finding_observations': finding_count, 'unique_resources_with_findings': unique_resources,
                          'full_inventory': False,
                          'message': ('This view includes only resources with saved findings in this scan. '
                                      'It is not a complete inventory assessment or proof the environment is healthy.')},
                services=sorted(rows, key=lambda r: (r['provider'], r['service_category'])),
                billed_spend_available=False, autonomous_execution=False)


def ai_context(finding, assessment):
    """An allowlist: never forward names, IDs, free-text details, raw tags or endpoints."""
    evidence = finding.get('evidence') or {}
    facts = {key: evidence[key] for key in ('encrypted', 'multi_az', 'publicly_accessible', 'deletion_protection', 'recent_snapshot_verified',
                    'imds_v2_required', 'public_admin_ingress', 'monitoring_enabled', 'tls_required',
                    'engine_supported', 'auto_minor_upgrade', 'health_probes_enabled', 'managed_secrets',
                    'flow_logs_enabled', 'public_snapshot','commitment_lock_conflict') if type(evidence.get(key)) is bool}
    for key in ('p95_usage', 'window_days', 'backup_retention_days', 'size_gb', 'provisioned_iops',
                'minimum_request', 'hosted_app_count', 'patch_age_days', 'unattached_days', 'snapshot_age_hours', 'stopped_days','cfs_throttling_p95_pct','oom_kill_count_30d','burst_credit_balance_min','surplus_credits_charged','disk_queue_length_p99','throttle_events','http_429_count','slo_burn_rate','disruptions_allowed'):
        value = number(evidence.get(key))
        if value is not None:
            facts[key] = value
    for key in ('window_start', 'window_end'):
        parsed = timestamp(evidence.get(key))
        if parsed is not None:
            facts[key] = parsed.isoformat()
    correlation=evidence.get('cpu_latency_correlation_r')
    if type(correlation) in (int,float) and -1<=correlation<=1:facts['cpu_latency_correlation_r']=correlation
    for key in ('samples', 'step_seconds'):
        if type(evidence.get(key)) is int and 0 <= evidence[key] <= 10_000_000:
            facts[key] = evidence[key]
    if evidence.get('percentile_method') == 'nearest_rank_0.95':
        facts['percentile_method'] = 'nearest_rank_0.95'
    for key, allowed in (('dimension', ('cpu', 'memory')), ('unit', ('cores', 'bytes'))):
        if evidence.get(key) in allowed:
            facts[key] = evidence[key]
    return dict(resource_reference=assessment['resource_key'], provider=finding.get('cloud_provider', 'azure'),
                service_category=assessment['service_category'], rule_id=finding['rule_id'], facts=facts,
                policy_version=POLICY_VERSION, observation=assessment['observation'], risk_floor=assessment['risk_level'],
                checks=[dict(pillar=p['pillar'], code=c['code'], status=c['status']) for p in assessment['pillars'] for c in p['checks'] if c['status']!='unknown' or c['code'] in MODEL_BASE_CODES],
                protected=bool(assessment['protected_reasons']), guardrails=assessment['guardrails'],
                observed_check_codes=[c['code'] for p in assessment['pillars'] for c in p['checks'] if c['status'] != 'unknown'])


def confidence(assessment):
    observation = assessment.get('observation') or {}
    if observation.get('status') != 'recent' or assessment.get('evidence_gap_codes'):
        return 'INSUFFICIENT_EVIDENCE'
    checks = [check for pillar in assessment.get('pillars', []) for check in pillar.get('checks', [])]
    observed = {check['code'] for check in checks if check['status'] != 'unknown'}
    if {'UTILIZATION_WINDOW', 'DEPENDENCY_GRAPH', 'BILLED_COST'} <= observed:
        # HIGH requires the new full telemetry contract, not the older 14-day Kubernetes summary.
        return 'MEDIUM'
    return 'LOW'
