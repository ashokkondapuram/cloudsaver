"""Server-evaluated Azure pilot evidence gates; no inference or provider mutation."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from app.control_plane.plans import digest
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series, moment

POLICY = {'id':'engineering-azure-pilot', 'version':1, 'minimum_days':14, 'minimum_coverage':.95,
          'maximum_gap_minutes':60, 'maximum_observation_age_hours':24, 'execution_enabled':False}
RULES = {'azure.vm.rightsize':'CS-AZ-VM-RIGHTSIZING', 'azure.disk.review':'CS-AZ-DISK-UNATTACHED'}
EVALUATOR_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def metric_gate(evidence, name, now):
    metrics = evidence.get('metrics')
    value = metrics.get(name) if isinstance(metrics, dict) else None
    if not isinstance(value, dict):
        return dict(status='unknown', reason='Historical samples are unavailable.', source='saved_observation')
    start, end = moment((value or {}).get('window_start')), moment((value or {}).get('window_end'))
    days = (end-start).total_seconds()/86400 if start and end else None
    if days is None or days != int(days) or not 14 <= days <= 30:
        return dict(status='unknown', reason='A representative 14–30 day raw sample window is required.', source='saved_observation')
    result = evaluate_series(value, TimeSeriesEvidenceContract(name, window_days=int(days)), now=now, require_resource_age=False)
    points = value.get('points')
    if isinstance(points, list) and any(type(p.get('value')) not in (int,float) or not 0 <= p['value'] <= 100 for p in points if isinstance(p,dict)):
        return dict(status='unknown', reason='Percentage samples must be within 0–100.', source='saved_observation')
    return dict(status='pass' if result.is_sufficient else 'unknown', reason=result.gap_reason or 'Raw samples meet the evidence contract; this is not candidate compatibility.',
                source='saved_observation', samples=result.valid_samples, expected_samples=result.expected_samples,
                coverage_ratio=result.coverage_ratio, p95=result.observed_value,
                window_start=start.isoformat(), window_end=end.isoformat(), aggregation_method='nearest_rank_p95_v1', source_resolution_seconds=300)


def evaluate(resource, scan, workload, *, action, candidate_sku=None, now=None, iac=None):
    now = now or datetime.now(timezone.utc)
    evidence = resource.get('evidence') if isinstance(resource.get('evidence'),dict) else {}
    at = moment(scan.get('timestamp'))
    checks = []
    def check(code, status, reason, source='saved_observation', **data):
        checks.append(dict(code=code, status=status, reason=reason, source=source, **data))
    check('OBSERVATION_FRESHNESS', 'pass' if at and 0 <= (now-at).total_seconds() <= 86400 else 'unknown',
          'The selected saved observation must be no more than 24 hours old and not future-dated.')
    check('OWNER', 'pass' if workload.get('owner') else 'unknown', 'Owner is a declaration, not verified identity or execution authority.', 'owner_declared')
    for code, field in [('APPLICATION_SLO','slo_reference'), ('PEAK_DEMAND','peak_reference'), ('RECOVERY_REQUIREMENTS','recovery_reference')]:
        check(code, 'unknown', 'A declared reference requires independently collected supporting evidence; it cannot prove a passing control.',
              'owner_declared', reference=workload.get('requirements',{}).get(field))
    tags = evidence.get('tags') if isinstance(evidence.get('tags'),dict) else {}
    protected = bool(evidence.get('management_locks')) or any(str(v).casefold() in ('true','yes','1') for k,v in tags.items() if str(k).casefold() in ('donotdelete','protected','legalhold'))
    check('PROTECTION', 'fail' if protected else 'unknown', 'Observed locks or retention intent block change.' if protected else 'Absence of returned protection is not a complete protection/hold assessment.')
    kind = resource.get('resource_type','').lower()
    expected = 'microsoft.compute/virtualmachines' if action == 'azure.vm.rightsize' else 'microsoft.compute/disks'
    check('APPLICABILITY', 'pass' if resource.get('cloud_provider','azure')=='azure' and kind==expected else 'not_applicable', 'The pilot action is limited to its exact Azure resource type.')
    if action == 'azure.vm.rightsize':
        for name in ('cpu_percent','memory_percent'):
            checks.append(dict(code=name.upper()+'_HISTORY', **metric_gate(evidence,name,now)))
        check('CANDIDATE_COMPATIBILITY','unknown', 'SKU architecture, quotas, availability, capacity, licensing and dependencies need authoritative verification.',
              'unverified_candidate', candidate_sku=candidate_sku)
    else:
        check('ATTACHMENT_HISTORY','unknown', 'Unattached state today does not prove sustained disuse or deletion eligibility.')
        check('RESTORE_VERIFICATION','unknown','A configured snapshot or backup is not proof of a tested restore.')
    check('IAC_OWNERSHIP','unknown', 'A registered mapping is a declaration until state ownership and competing states are verified.',
          'operator_declared' if iac else 'missing', mapping=iac)
    for code, reason in [('RESOURCE_INCARNATION','Stable provider ID alone does not establish resource incarnation.'),
                         ('TRUSTED_TERRAFORM_PLAN','A protected pipeline must attest the exact saved plan, state and provider/input hashes.'),
                         ('FINANCIAL_RECONCILIATION','Complete comparable billing, commitments and demand adjustment are required.'),
                         ('SANDBOX_ACCEPTANCE','This action has no authorized sandbox acceptance in this environment.')]:
        check(code,'unknown',reason,'not_collected')
    stable = {'scan_id':scan['scan_id'], 'resource':resource, 'workload_id':workload['id'], 'workload_version':workload['version'],
              'requirements':workload['requirements'], 'policy':POLICY, 'evaluator_digest':EVALUATOR_DIGEST, 'action':action, 'candidate_sku':candidate_sku, 'iac':iac}
    status = 'not_applicable' if any(c['code']=='APPLICABILITY' and c['status']=='not_applicable' for c in checks) else 'blocked' if any(c['status']=='fail' for c in checks) else 'evidence_required'
    return dict(schema_version=1, rule_id=RULES[action], rule_version='1', evaluator_digest=EVALUATOR_DIGEST, decision=status, checks=checks,
                evidence_digest=digest(stable), policy_digest=digest(POLICY), evaluated_at=now.isoformat(),
                automatic_execution=False, execution_enabled=False,
                financial_outcome={'estimated_opportunity':None,'validated_run_rate':None,'reconciled_benefit':None},
                next_steps=['Collect missing historical and workload evidence.', 'Verify IaC ownership and the resource incarnation.',
                            'Prepare a customer-reviewed Terraform change in the registered repository.',
                            'Use independent approval and a protected pipeline before any apply.',
                            'Verify application/infrastructure outcomes and reconcile billing separately.'])
