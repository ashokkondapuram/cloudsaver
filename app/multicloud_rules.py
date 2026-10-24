"""Concrete conservative reviews; no fabricated prices, telemetry or execution authority."""
from datetime import datetime,timezone
from app.resource_catalog import family,definitions
from app.telemetry_contract import moment
from app.assessment import protection

def slo_gate(e,now):
    if isinstance(e.get('slo_evidence'),dict):
        from app.causal_topology_simulator import evaluate_slo_bounded_rightsizing
        try:
            if evaluate_slo_bounded_rightsizing(e['slo_evidence'],now=now)['status']!='review_eligible':return False
        except (ValueError,TypeError):return False
    stamp=moment(e.get('slo_observed_at'));burn=e.get('slo_burn_rate');correlation=e.get('cpu_latency_correlation_r')
    if not stamp or not 0<=(now-stamp).total_seconds()<86400 or type(burn) not in (int,float) or type(correlation) not in (int,float):return None
    import math
    if not math.isfinite(burn) or not 0<=burn or not math.isfinite(correlation) or not -1<=correlation<=1:return None
    return burn<=1 and correlation<=.60 and e.get('oom_kill_count_30d',0)==0 and e.get('cfs_throttling_p95_pct',0)<=2

def condition(rid,e,p,now):
    from app.analysis_rules import series,continuous
    def metric(key,stat='p95'):
        data=series((e.get('metrics') or {}).get(key),now)
        return data[stat] if data else None
    def low(key,limit,stat='p95'):
        v=metric(key,stat);return None if v is None else v<limit
    def all_known(*values):return None if any(type(v) is not bool for v in values) else all(values)
    def rightsize(cpu=20,memory=45):
        return all_known(low('cpu_percent',p.get('utilization_percent',cpu)),low('memory_percent',memory),slo_gate(e,now),e.get('target_compatible') if type(e.get('target_compatible')) is bool else None)
    def retained(state,days=14,snapshot=False):
        history=continuous(e,state,p.get('minimum_days',days),now)
        if not snapshot:return history
        age=e.get('snapshot_age_hours')
        verified=None if type(age) not in (int,float) or type(e.get('recent_snapshot_verified')) is not bool else e['recent_snapshot_verified'] and 0<=age<24
        return all_known(history,verified)
    def empty_backend():return all_known(e.get('dependencies_verified') if type(e.get('dependencies_verified')) is bool else None,
        low('requests',1,'maximum'),low('healthy_targets',1,'maximum'),retained('Empty',7))
    if rid in ('AWS_UNATTACHED_EBS','GCP_UNATTACHED_DISK'):return retained('Unattached',snapshot=True) if e.get('disk_state') in ('Unattached','available','READY') else False if e.get('disk_state') in ('Attached','in-use') else None
    if rid in ('AWS_UNASSOCIATED_EIP','GCP_UNASSIGNED_ADDRESS'):
        return retained('Unassociated',7) if e.get('association_verified') is False else False if e.get('association_verified') is True else None
    if rid in ('AWS_EC2_STOPPED_EBS_RESIDUAL','GCP_GCE_STOPPED_DISK_TAX'):return retained('Stopped') if e.get('power_state') in ('stopped','TERMINATED') else False if e.get('power_state') in ('running','RUNNING') else None
    if rid in ('AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING','GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING'):return rightsize(15,45)
    if rid in ('AWS_EBS_GP2_TO_GP3_AND_IOPS_TUNING','GCP_DISK_HYPERDISK_IOPS_TUNING'):
        target=e.get('target_disk') or {};io=metric('iops','p99');throughput=metric('throughput','p99')
        if io is None or throughput is None or not all(type(target.get(k)) in (int,float) and target[k]>0 for k in ('iops','throughput')):return None
        return all_known(io*(1+p.get('headroom_percent',30)/100)<=target['iops'],throughput*(1+p.get('headroom_percent',30)/100)<=target['throughput'],e.get('target_compatible'),e.get('throttling_observed') is False if 'throttling_observed' in e else None)
    if rid in ('AZURE_SQL_PG_IDLE_AND_NONPROD_HA_REVIEW','AWS_RDS_AURORA_RIGHTSIZING_AND_GP3','GCP_CLOUDSQL_ALLOYDB_RIGHTSIZING_AND_HA'):
        return rightsize(20,45)
    if rid=='AWS_IDLE_RDS':return retained('Stopped',7) if e.get('power_state')=='stopped' else all_known(e.get('nonproduction'),low('connections',1,'maximum'),low('cpu_percent',5))
    if rid=='GCP_IDLE_CLOUD_SQL':return e.get('aligned_hours')==336 and e.get('maximum_connections')==0 if 'aligned_hours' in e else None
    if rid in ('AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR','AWS_ELB_ORPHANED_AND_INGRESS_CONSOLIDATION','GCP_LB_EMPTY_BACKEND_FORWARDING_RULE'):return empty_backend()
    if rid in ('AZURE_NAT_GATEWAY_SERVICE_ENDPOINT_BYPASS','AWS_NAT_GW_ENDPOINT_BYPASS_AND_IDLE','GCP_CLOUD_NAT_PRIVATE_GOOGLE_ACCESS'):
        if e.get('routing_verified') is not True or e.get('flow_log_coverage_ratio',0)<.95:return None
        return metric('endpoint_eligible_bytes','maximum')>0 if metric('endpoint_eligible_bytes','maximum') is not None else None
    if rid=='AZURE_COSMOSDB_MANUAL_RU_TO_AUTOSCALE':
        values=series((e.get('metrics') or {}).get('normalized_ru_consumption'),now)
        mean=e.get('ru_average_percent')
        return None if not values or type(mean) not in (int,float) or mean<=0 or 'manual_throughput' not in e else e['manual_throughput'] is True and values['p99']<p.get('utilization_percent',30) and values['maximum']/mean>3
    if rid in ('AZURE_REDIS_UNDERUTILIZED_TIER_REVIEW','AWS_ELASTICACHE_GRAVITON_AND_VALKEY_UPGRADE'):
        return all_known(low('memory_percent',35,'p99'),low('cpu_percent',p.get('utilization_percent',25)),low('evictions',1,'maximum'),e.get('target_compatible'))
    if rid=='AWS_DYNAMODB_BILLING_MODE_AND_UNUSED_GSI':return all_known(low('read_utilization_percent',p.get('utilization_percent',18)),low('write_utilization_percent',p.get('utilization_percent',18)),low('throttle_events',1,'maximum'),e.get('spiky_traffic_verified'))
    if rid=='AWS_LAMBDA_ARM64_AND_PROVISIONED_CONCURRENCY':return all_known(low('provisioned_concurrency_utilization',p.get('utilization_percent',15)),e.get('target_compatible'),slo_gate(e,now))
    if rid in ('AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD','AWS_S3_INTELLIGENT_TIERING_AND_MULTIPART_CLEANUP'):
        if type(e.get('abort_incomplete_multipart_days')) is int:return e['abort_incomplete_multipart_days']>7
        if e.get('lifecycle_policy_verified') is True and e.get('multipart_abort_rule_present') is False:return True
        return None
    if rid in ('AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE','AWS_BEDROCK_PT_AND_SAGEMAKER_IDLE_ENDPOINT','GCP_VERTEX_AI_IDLE_ENDPOINT_AND_REPLICA_FLOOR'):
        if rid=='AZURE_AI_FOUNDRY_PTU_VS_PAYG_ARBITRAGE' or e.get('provisioned_mode') is True:
            from app.ai_capacity import ptu_review
            return ptu_review(e,now,p.get('utilization_percent',35))
        if e.get('commitment_lock_conflict') is True:return False
        if e.get('dependencies_verified') is not True:return None
        return low('invocations',1,'maximum')
    if rid=='GCP_BIGQUERY_SLOT_AUTOSCALE_AND_STORAGE':return all_known(low('slot_utilization_percent',p.get('utilization_percent',25)),e.get('target_compatible'),e.get('commitment_lock_conflict') is False if 'commitment_lock_conflict' in e else None)
    if rid=='GCP_CLOUDRUN_MIN_INSTANCE_AND_MEMORYSTORE':return all_known(low('requests',1,'maximum'),e.get('nonproduction'),e.get('minimum_instances',0)>0 if type(e.get('minimum_instances')) is int else None)
    return None

def evaluate_inventory(inventory,*,policies=None,observed_at=None,now=None,providers=None):
    from app.analysis_rules import RULES as LEGACY
    now=now or datetime.now(timezone.utc);legacy={r[0] for r in LEGACY};lookup={r[0]:r for r in definitions()};result=[]
    for resource in inventory:
        f=family(resource)
        if not f or f[0]=='kubernetes' or providers and f[0] not in providers:continue
        for rid in f[4]:
            if rid in legacy:continue
            rule=lookup[rid];policy=(policies or {}).get(rid,{})
            output=dict(rule_id=rid,rule_version='1.4.0',name=rule[4],cloud_provider=f[0],resource_id=resource['resource_id'],
                resource_type=resource['resource_type'],subscription_id=resource.get('subscription_id'),scope_id=resource.get('scope_id'),
                outcome='insufficient_evidence',reason='Complete fresh history, telemetry and target proof are required.',
                automatic_execution=False,estimated_savings=None,protected_reasons=protection(resource),destructive_actions_blocked=True)
            stamp=moment(observed_at or resource.get('observed_at'));e=resource.get('evidence') or {}
            if policy.get('enabled') is False or policy.get('unavailable_reason'):output.update(outcome='disabled_by_policy',reason='Disabled under frozen workspace policy.')
            elif resource.get('reconciliation_status')=='source_conflict':output['reason']='Conflicting evidence requires reconciliation.'
            elif stamp and 0<=(now-stamp).total_seconds()<86400:
                try:
                    bounds=rule[6];params={k:v[0] for k,v in bounds.items()};supplied=policy.get('parameters') or {}
                    if set(supplied)-set(bounds) or any(type(v) is not int or not bounds[k][1]<=v<=bounds[k][2] for k,v in supplied.items()):raise ValueError('Invalid parameters')
                    params.update(supplied);detected=condition(rid,e,params,now)
                    if type(detected) is bool:output.update(outcome='condition_detected' if detected else 'condition_not_detected',reason='Evidence supports a review; changes and cash savings require independent approval.' if detected else 'The measured condition was not detected.')
                except (TypeError,ValueError,KeyError,OverflowError):output.update(outcome='evaluation_failed',reason='Invalid evidence or rule parameter.')
            result.append(output)
    return result

def findings(inventory,now):
    """Materialize proven review conditions only. Telemetry gaps never create waste."""
    rows={r['resource_id']:r for r in inventory};out=[]
    for result in evaluate_inventory(inventory,observed_at=now.isoformat(),now=now):
        if result['outcome']!='condition_detected':continue
        r=rows[result['resource_id']]
        out.append(dict(r,rule_id=result['rule_id'],severity='MEDIUM',details=result['reason'],estimated_monthly_waste_usd=None))
    return out

def materialize(existing,inventory,outcomes):
    from app.resource_catalog import definitions
    supported={r[0] for r in definitions()};seen={(r.get('cloud_provider','azure'),r['resource_id'],r['rule_id']) for r in existing}
    resources={(r.get('cloud_provider','azure'),r['resource_id']):r for r in inventory};result=list(existing)
    for outcome in outcomes:
        key=(outcome.get('cloud_provider','azure'),outcome['resource_id'],outcome['rule_id'])
        if outcome['rule_id'] not in supported or outcome['outcome']!='condition_detected' or key in seen:continue
        resource=resources.get(key[:2])
        if resource:
            from app.pricing import attribute_finding_cost
            result.append(attribute_finding_cost(dict(resource,rule_id=outcome['rule_id'],severity='MEDIUM',details=outcome['reason'],estimated_monthly_waste_usd=None)));seen.add(key)
    return result
