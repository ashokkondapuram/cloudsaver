"""Eight Kubernetes review contracts. Findings are never execution approvals or cash savings."""
from datetime import datetime, timedelta, timezone
from app.assessment import protection
from app.telemetry_contract import moment

VERSION = 'kubernetes-2026-10-24.1'
DEFINITIONS = (
    ('K8S_CONTAINER_CPU_OVERREQUEST', ('Container',), 'Container CPU request rightsizing review', 'cost'),
    ('K8S_CONTAINER_MEMORY_OVERREQUEST', ('Container',), 'Container memory working-set rightsizing review', 'cost'),
    ('K8S_CONTAINER_UNDERPROVISIONED_RISK', ('Container',), 'Throttling, OOM and QoS reliability review', 'reliability'),
    ('K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR', ('HorizontalPodAutoscaler','PodDisruptionBudget'), 'Autoscaler floor and PDB lock review', 'operations'),
    ('K8S_NODE_POOL_FRAGMENTATION_WASTE', ('Node',), 'Node capacity reservation slack review', 'cost'),
    ('K8S_ABANDONED_WORKLOAD_OR_NAMESPACE', ('Container',), 'Zero-traffic workload review', 'operations'),
    ('K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY', ('PersistentVolumeClaim',), 'Unmounted or low-occupancy PVC review', 'cost'),
    ('K8S_ORPHANED_LOADBALANCER_SERVICE', ('Service',), 'Empty-endpoint LoadBalancer service review', 'cost'),
)
RULE_IDS = {r[0] for r in DEFINITIONS}


def evaluate(resource, rule, *, policy=None, observed_at=None, now=None):
    now = now or datetime.now(timezone.utc)
    rid, kinds, name, pillar = rule
    e = resource.get('evidence') or {}
    metrics = e.get('metrics') or {}
    output = dict(rule_id=rid, rule_version=VERSION, name=name, pillar=pillar, cloud_provider='kubernetes',
        resource_id=resource['resource_id'], subscription_id=resource.get('subscription_id'), scope_id=resource.get('scope_id'),
        resource_type=resource['resource_type'], outcome='insufficient_evidence',
        reason='Required complete inventory or historical telemetry is unavailable.',
        automatic_execution=False, estimated_savings=None, allocation_opportunity_usd=None, realizable_node_savings_usd=None,
        protected_reasons=protection(resource), destructive_actions_blocked=True, safety_blocks=[], recommendation=None)
    def finish(detected, reason, blocks=(), recommendation=None):
        return dict(output, outcome='condition_detected' if detected else 'condition_not_detected', reason=reason,
            safety_blocks=list(blocks), recommendation=recommendation)
    if policy and (policy.get('enabled') is False or policy.get('unavailable_reason')):
        return dict(output,outcome='disabled_by_policy',reason='Disabled under frozen workspace rule policy.')
    stamp = moment(observed_at or resource.get('observed_at'))
    if not stamp or not 0 <= (now-stamp).total_seconds() < 86400:
        return dict(output,reason='Inventory observation is stale or unverified.')
    if resource.get('reconciliation_status') == 'source_conflict':
        return dict(output,reason='Conflicting sources block this evaluation.',safety_blocks=['SOURCE_CONFLICT'])
    def stat(name):
        value = metrics.get(name)
        end = moment(value.get('window_end')) if isinstance(value,dict) else None
        return value if isinstance(value,dict) and value.get('sufficient') is True and end and 0 <= (now-end).total_seconds() < 86400 else None
    cpu, memory, throttle, oom, restarts = (stat(name) for name in ('cpu','memory','throttling','oom','restarts'))
    created=moment(e.get('created_at'))
    mature=bool(created and now-created>=timedelta(days=30))
    if rid == 'K8S_CONTAINER_CPU_OVERREQUEST':
        requests=stat('cpu_request')
        current=e.get('cpu_request')
        if not mature or not cpu or not throttle or not requests or type(current) not in (int,float) or e.get('hpa_present') is None or not e.get('controller'):
            return output
        if requests['minimum'] != current or requests['maximum'] != current:
            return dict(output,reason='CPU request changed during the telemetry window.')
        target=cpu['p95']*1.5
        detected=current>target and current-target>.1
        blocks=[]
        if throttle['p95']>.02: blocks.append('CPU_THROTTLING_ABOVE_2_PERCENT')
        if e['hpa_present']: blocks.append('COORDINATED_HPA_REVIEW_REQUIRED')
        return finish(detected,'CPU request exceeds P95 plus 50% headroom by more than 100m per replica.' if detected else 'The CPU overrequest condition was not detected.',blocks,
            dict(cpu_request_cores=target) if detected and not blocks and target>0 else None)
    if rid == 'K8S_CONTAINER_MEMORY_OVERREQUEST':
        requests=stat('memory_request');current=e.get('memory_request')
        if not mature or not memory or not oom or not restarts or not requests or type(current) not in (int,float) or not e.get('controller'):
            return output
        if requests['minimum'] != current or requests['maximum'] != current:
            return dict(output,reason='Memory request changed during the telemetry window.')
        target=memory['p99']*1.35;detected=current>target and current-target>256*1024**2
        blocks=[]
        if oom['maximum']>0: blocks.append('OOMKILL_OBSERVED')
        elif restarts['maximum'] != restarts['minimum']: blocks.append('RESTART_HISTORY_REQUIRES_OOM_VERIFICATION')
        if e.get('fixed_heap_configured'): blocks.append('COORDINATED_RUNTIME_HEAP_REVIEW_REQUIRED')
        return finish(detected,'Memory request exceeds P99 working set plus 35% by more than 256 MiB.' if detected else 'The memory overrequest condition was not detected.',blocks,
            dict(memory_request_bytes=target) if detected and not blocks and target>0 else None)
    if rid == 'K8S_CONTAINER_UNDERPROVISIONED_RISK':
        reasons=[]
        if oom and oom['maximum']>0: reasons.append('OOMKILL_OBSERVED')
        if throttle and throttle['p95']>.10: reasons.append('CPU_THROTTLING_ABOVE_10_PERCENT')
        limit=e.get('memory_limit')
        if memory and type(limit) in (int,float) and limit>0 and memory['p95']>.9*limit: reasons.append('MEMORY_NEAR_LIMIT')
        if e.get('production') and e.get('qos_class')=='BestEffort': reasons.append('PRODUCTION_BESTEFFORT_QOS')
        if reasons:
            return dict(finish(True,'Reliability or performance risk requires review.',reasons),estimated_savings=0)
        return finish(False,'No measured underprovisioning trigger.') if oom and throttle and memory and type(limit) in (int,float) and limit>0 else output
    if rid == 'K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR':
        if resource['resource_type'].endswith('/PodDisruptionBudget'):
            if type(e.get('disruptions_allowed')) is int and type(e.get('expected_pods')) is int and type(e.get('generation')) is int and e.get('observed_generation')==e.get('generation'):
                return finish(e['disruptions_allowed']==0 and e['expected_pods']>0,'Current PDB disruption allowance; a zero allowance requires consolidation review, not automatic relaxation.')
        return dict(output,reason='Historical min-replica and utilization evidence is required; a current HPA floor is not proof of 14-day idle capacity.')
    if rid == 'K8S_NODE_POOL_FRAGMENTATION_WASTE':
        pool=e.get('pool_capacity') or {}
        cpu_capacity,memory_capacity=pool.get('allocatable_cpu'),pool.get('allocatable_memory')
        if pool.get('complete') is not True or not all(type(v) in (int,float) and v>0 for v in (cpu_capacity,memory_capacity)):
            return output
        cpu_ratio=pool['requested_cpu']/cpu_capacity;memory_ratio=pool['requested_memory']/memory_capacity
        result=finish(cpu_ratio<.45 and memory_ratio<.45,'Reservation slack is an allocation review signal. Node termination, packing feasibility, PDBs and actual utilization remain unverified.', ['NODE_CONSOLIDATION_REQUIRES_SCHEDULING_REVIEW'])
        return dict(result,capacity={'cpu_request_ratio':cpu_ratio,'memory_request_ratio':memory_ratio,
            'daemonset_cpu_tax_ratio':pool['daemon_cpu']/cpu_capacity,'daemonset_memory_tax_ratio':pool['daemon_memory']/memory_capacity})
    if rid == 'K8S_ABANDONED_WORKLOAD_OR_NAMESPACE':
        network=stat('network')
        if e.get('namespace') in ('kube-system','kube-public','kube-node-lease'):
            return dict(output,outcome='not_applicable',reason='System workloads are excluded from abandonment review.')
        if not mature or not cpu or not network or not e.get('controller'):
            return output
        return finish(cpu['maximum']==0 and network['maximum']==0,'30-day observed CPU/network inactivity is a review signal; verify jobs, recovery intent and application demand.', ['APPLICATION_OWNER_APPROVAL_REQUIRED'])
    if rid == 'K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY':
        occupancy=stat('occupancy');mounts=stat('mounts')
        orphan=(e.get('phase')=='Bound' and e.get('cronjob_inventory_complete') is True and not e.get('cronjob_reference')
            and e.get('mounted_by_current_pods')==[] and mounts and mounts['maximum']==0)
        size=e.get('capacity_bytes')
        low=occupancy and type(size) in (int,float) and size>=100*1024**3 and occupancy['p99']<.10
        if orphan or low:
            return finish(True,'Historical mount or occupancy evidence requires volume migration/recovery review. Expansion support does not imply in-place shrink support.', ['CSI_MIGRATION_AND_RECOVERY_REVIEW_REQUIRED'])
        if occupancy and mounts:
            return finish(False,'Available mount and occupancy evidence does not meet a PVC review condition.')
        return output
    if rid == 'K8S_ORPHANED_LOADBALANCER_SERVICE':
        if e.get('service_type')!='LoadBalancer':
            return dict(output,outcome='not_applicable',reason='This rule evaluates LoadBalancer services.')
        endpoints=stat('endpoints')
        if not endpoints or type(e.get('available_endpoints')) is not int or e.get('cloud_lb_observed') is not True:
            return output
        return finish(endpoints['maximum']==0 and e['available_endpoints']==0,'30-day endpoint evidence is available. Paid cloud LB identity and retained ingress intent require review.', ['CLOUD_LB_COST_AND_OWNERSHIP_REVIEW_REQUIRED'])
    return output


def evaluate_inventory(inventory, *, policies=None, observed_at=None, now=None):
    outcomes=[]
    for row in inventory:
        if row.get('cloud_provider')!='kubernetes': continue
        kind=row['resource_type'].split('/')[-1]
        for rule in DEFINITIONS:
            if kind not in rule[1]: continue
            try:
                outcomes.append(evaluate(row,rule,policy=(policies or {}).get(rule[0]),observed_at=observed_at,now=now))
            except (KeyError,TypeError,ValueError,OverflowError):
                outcomes.append(dict(rule_id=rule[0],rule_version=VERSION,resource_id=row['resource_id'],subscription_id=row.get('subscription_id'),
                    cloud_provider='kubernetes',outcome='evaluation_failed',reason='Invalid evidence; independent inspection is required.',automatic_execution=False))
    return outcomes


def findings_from(outcomes, inventory):
    resources={r['resource_id']:r for r in inventory}
    results=[]
    for evaluation in outcomes:
        if evaluation['outcome']!='condition_detected': continue
        row=resources[evaluation['resource_id']]
        results.append(dict(rule_id=evaluation['rule_id'],cloud_provider='kubernetes',scope_id=row['scope_id'],subscription_id=row['subscription_id'],
            resource_id=row['resource_id'],resource_type=row['resource_type'],resource_name=row['resource_name'],resource_group=row['resource_group'],
            severity='HIGH' if evaluation['rule_id']=='K8S_CONTAINER_UNDERPROVISIONED_RISK' else 'MEDIUM',estimated_monthly_waste_usd=None,
            details=evaluation['reason'],evidence=dict(row['evidence'],rule_evaluation=evaluation),
            data_sources=row.get('data_sources',[]),reconciliation_status=row.get('reconciliation_status','partial_telemetry')))
    return results
