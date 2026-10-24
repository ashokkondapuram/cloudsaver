"""Allowlisted Kubernetes object projection; commands, env values and Secret data stay out."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re

from app.collectors.kubernetes import VERSION


def quantity(value):
    if value is None:
        return None
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(n|u|m|k|K|M|G|T|P|E|Ki|Mi|Gi|Ti|Pi|Ei)?', str(value))
    if not match:
        return None
    factors = {'n': Decimal('0.000000001'), 'u': Decimal('0.000001'), 'm': Decimal('.001'),
        **{suffix: Decimal(1000)**i for i,suffix in enumerate(('', 'k', 'M', 'G', 'T', 'P', 'E'))},
        **{suffix: Decimal(1024)**i for i,suffix in enumerate(('', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei'))}, 'K': Decimal(1000)}
    try:
        result = Decimal(match[1]) * factors[match[2] or '']
        return float(result) if result.is_finite() and result <= Decimal('1e30') else None
    except (InvalidOperation, OverflowError):
        return None


def resource_id(cluster, kind, namespace, name):
    return f'k8s://{cluster}/' + (f'namespaces/{namespace}/' if namespace else '') + kind.lower() + 's/' + name


def project(cluster, objects, metrics, sources, now):
    rows, by_kind, by_name = [], {}, {}
    stamp = now.isoformat()
    for kind, values in objects.items():
        by_kind[kind] = values
        for item in values or []:
            meta = item['metadata']
            by_name[(kind, meta.get('namespace'), meta['name'])] = item

    def owner(pod,seen=None):
        meta = pod['metadata']
        refs = [r for r in meta.get('ownerReferences', []) if r.get('controller') is True]
        if len(refs) != 1:
            return None
        ref = refs[0]
        seen=set() if seen is None else seen
        if ref.get('uid') in seen:return None
        seen.add(ref.get('uid'))
        parent = by_name.get((ref['kind'], meta['namespace'], ref['name']))
        if not parent or parent['metadata']['uid'] != ref.get('uid'):
            return None
        if ref['kind'] == 'ReplicaSet':
            return owner(parent,seen)
        return {'kind': ref['kind'], 'name': ref['name'], 'uid': ref['uid']}

    def make(kind, meta, evidence):
        namespace = meta.get('namespace')
        rid = resource_id(cluster, kind, namespace, meta['name'])
        inherited=by_name.get(('Namespace',None,namespace),{}).get('metadata',{}).get('labels',{})
        labels=dict(inherited,**meta.get('labels',{}))
        return dict(cloud_provider='kubernetes', scope_id=cluster, subscription_id=cluster, resource_id=rid,
            resource_name=meta['name'], resource_group=namespace or cluster, resource_type='kubernetes.io/' + kind,
            inventory_rule_id='K8S_INVENTORY', collector_version=VERSION, observed_at=stamp,
            data_sources=sources, reconciliation_status='partial_telemetry',
            evidence=dict(created_at=meta.get('creationTimestamp'), uid=meta['uid'], namespace=namespace,
                labels={k:v for k,v in labels.items() if k in ('environment', 'env', 'app', 'team', 'retain', 'DoNotDelete', 'role') and isinstance(v,str)}, **evidence))

    active = [p for p in objects['Pod'] if p.get('status',{}).get('phase') not in ('Succeeded', 'Failed')]
    requested = defaultdict(lambda: {'cpu': 0., 'memory': 0., 'daemon_cpu': 0., 'daemon_memory': 0., 'complete': True})
    mounts = defaultdict(set)
    for pod in active:
        spec, meta = pod.get('spec',{}), pod['metadata']
        controller = owner(pod)
        node = spec.get('nodeName')
        for volume in spec.get('volumes', []):
            claim = volume.get('persistentVolumeClaim',{}).get('claimName')
            if claim:
                mounts[(meta['namespace'],claim)].add(meta['name'])
        for dimension in ('cpu', 'memory'):
            standard = [quantity(c.get('resources',{}).get('requests',{}).get(dimension)) for c in spec.get('containers', [])]
            init = [quantity(c.get('resources',{}).get('requests',{}).get(dimension)) for c in spec.get('initContainers', [])]
            # Restartable init containers require Kubernetes scheduling semantics beyond max-init.
            if any(c.get('restartPolicy') == 'Always' for c in spec.get('initContainers',[])) or any(v is None for v in standard+init):
                requested[node]['complete'] = False
            amount = max(sum(v or 0 for v in standard), max((v or 0 for v in init), default=0)) + (quantity(spec.get('overhead',{}).get(dimension)) or 0)
            requested[node][dimension] += amount
            if controller and controller['kind'] == 'DaemonSet':
                requested[node]['daemon_'+dimension] += amount

    for kind, values in objects.items():
        for item in values or []:
            meta, spec, status = item['metadata'], item.get('spec',{}), item.get('status',{})
            evidence = {}
            if kind == 'Node':
                evidence.update(node_pool=meta.get('labels',{}).get('agentpool') or meta.get('labels',{}).get('eks.amazonaws.com/nodegroup') or meta.get('labels',{}).get('cloud.google.com/gke-nodepool') or meta.get('labels',{}).get('cloudsaver.io/node-pool'),
                    provider_id=spec.get('providerID'), allocatable_cpu=quantity(status.get('allocatable',{}).get('cpu')),
                    allocatable_memory=quantity(status.get('allocatable',{}).get('memory')), requests=requested[meta['name']],
                    unschedulable=spec.get('unschedulable',False), taint_count=len(spec.get('taints',[])),
                    pdb_inventory_complete=objects.get('PodDisruptionBudget') is not None)
            elif kind == 'PersistentVolumeClaim':
                key=(meta['namespace'],meta['name'])
                evidence.update(phase=status.get('phase'), volume_name=spec.get('volumeName'), storage_class=spec.get('storageClassName'),
                    capacity_bytes=quantity(status.get('capacity',{}).get('storage')), mounted_by_current_pods=sorted(mounts[key]),
                    cronjob_inventory_complete=objects.get('CronJob') is not None,
                    cronjob_reference=any(v.get('persistentVolumeClaim',{}).get('claimName') == meta['name'] for j in objects.get('CronJob') or [] if j['metadata']['namespace']==meta['namespace'] for v in j.get('spec',{}).get('jobTemplate',{}).get('spec',{}).get('template',{}).get('spec',{}).get('volumes',[])),
                    metrics={name:metrics.get(source,{}).get(key) for name,source in [('occupancy','pvc_occupancy'),('mounts','pvc_mounts')]})
            elif kind == 'Service':
                key=(meta['namespace'],meta['name'])
                slices = objects.get('EndpointSlice')
                evidence.update(service_type=spec.get('type'), cloud_lb_observed=bool(status.get('loadBalancer',{}).get('ingress')),
                    available_endpoints=None if slices is None else sum(1 for s in slices if s['metadata'].get('namespace')==meta['namespace'] and s['metadata'].get('labels',{}).get('kubernetes.io/service-name')==meta['name'] for e in s.get('endpoints',[]) if e.get('conditions',{}).get('ready') is True),
                    metrics={'endpoints':metrics.get('service_endpoints',{}).get(key)})
            elif kind == 'PodDisruptionBudget':
                evidence.update(disruptions_allowed=status.get('disruptionsAllowed'), expected_pods=status.get('expectedPods'),
                    observed_generation=status.get('observedGeneration'), generation=meta.get('generation'))
            elif kind == 'HorizontalPodAutoscaler':
                evidence.update(min_replicas=spec.get('minReplicas',1), max_replicas=spec.get('maxReplicas'), current_replicas=status.get('currentReplicas'),
                    target=spec.get('scaleTargetRef'), metric_targets=[m.get('resource') for m in spec.get('metrics',[]) if m.get('type')=='Resource'])
            elif kind in ('Deployment','StatefulSet','DaemonSet'):
                evidence.update(replicas=spec.get('replicas'), available_replicas=status.get('availableReplicas'),
                    desired_replicas=status.get('desiredNumberScheduled') if kind=='DaemonSet' else spec.get('replicas',1),
                    template_generation=meta.get('generation'))
                if kind=='StatefulSet':
                    labels=spec.get('template',{}).get('metadata',{}).get('labels',{});pdbs=objects.get('PodDisruptionBudget')
                    evidence.update(volume_claim_templates=[dict(name=t.get('metadata',{}).get('name'),storage_class=t.get('spec',{}).get('storageClassName'),requested_bytes=quantity(t.get('spec',{}).get('resources',{}).get('requests',{}).get('storage'))) for t in spec.get('volumeClaimTemplates',[])],
                        topology_spread_constraints_present=bool(spec.get('template',{}).get('spec',{}).get('topologySpreadConstraints')),
                        pdb_inventory_complete=pdbs is not None,pdb_present=None if pdbs is None else any(p['metadata']['namespace']==meta['namespace'] and not p.get('spec',{}).get('selector',{}).get('matchExpressions') and all(labels.get(k)==v for k,v in p.get('spec',{}).get('selector',{}).get('matchLabels',{}).items()) for p in pdbs))
            elif kind in ('CronJob','Job'):
                jobs=objects.get('Job');owned=[j for j in jobs or [] if j['metadata'].get('namespace')==meta['namespace'] and (kind=='Job' and j['metadata']['uid']==meta['uid'] or kind=='CronJob' and any(o.get('uid')==meta['uid'] and o.get('controller') is True for o in j['metadata'].get('ownerReferences',[])))]
                job_spec=spec.get('jobTemplate',{}).get('spec',{}) if kind=='CronJob' else spec
                evidence.update(job_inventory_complete=jobs is not None,ttl_seconds_after_finished=job_spec.get('ttlSecondsAfterFinished'),
                    completed_jobs=sum(bool(j.get('status',{}).get('completionTime')) for j in owned),backoff_exceeded_jobs=sum(any(c.get('reason')=='BackoffLimitExceeded' and c.get('status')=='True' for c in j.get('status',{}).get('conditions',[])) for j in owned))
            elif kind == 'PersistentVolume':
                evidence.update(phase=status.get('phase'), storage_class=spec.get('storageClassName'), csi_driver=spec.get('csi',{}).get('driver'),csi_volume_handle=spec.get('csi',{}).get('volumeHandle'))
            elif kind == 'StorageClass':
                evidence.update(expansion_supported=item.get('allowVolumeExpansion') is True, provisioner=item.get('provisioner'))
            rows.append(make(kind,meta,evidence))
            if kind != 'Pod' or item not in active:
                continue
            controller = owner(item)
            namespace = meta['namespace']
            hpas = objects.get('HorizontalPodAutoscaler')
            associated_hpa = None if hpas is None or not controller else any(h['metadata']['namespace']==namespace and h.get('spec',{}).get('scaleTargetRef',{}).get('name')==controller['name'] and h.get('spec',{}).get('scaleTargetRef',{}).get('kind')==controller['kind'] for h in hpas)
            for container in spec.get('containers',[]):
                name=container['name']; key=(namespace,meta['name'],name)
                details = dict(pod=meta['name'], container=name, node=spec.get('nodeName'), controller=controller,
                    qos_class=status.get('qosClass'), production=any(meta.get('labels',{}).get(k) in ('prod','production') for k in ('environment','env')),
                    cpu_request=quantity(container.get('resources',{}).get('requests',{}).get('cpu')),
                    memory_request=quantity(container.get('resources',{}).get('requests',{}).get('memory')),
                    memory_limit=quantity(container.get('resources',{}).get('limits',{}).get('memory')),
                    fixed_heap_configured=any('-Xmx' in str(a) or 'GOMEMLIMIT' in str(a) for a in container.get('command',[])+container.get('args',[])) or any(e.get('name') in ('GOMEMLIMIT','JAVA_TOOL_OPTIONS','JAVA_OPTS') for e in container.get('env',[])),
                    hpa_present=associated_hpa, metrics={name:metrics.get(name,{}).get(key) for name in ('cpu','memory','throttling','cpu_request','memory_request','oom','restarts')})
                details['metrics']['network']=metrics.get('network',{}).get((namespace,meta['name']))
                row=make('Container',meta,details)
                row['evidence']['production']=any(row['evidence']['labels'].get(k) in ('prod','production') for k in ('environment','env'))
                row.update(resource_id=f'k8s://{cluster}/namespaces/{namespace}/pods/{meta["name"]}/containers/{name}',resource_name=name)
                rows.append(row)
    pools=defaultdict(list)
    for row in rows:
        if row['resource_type']=='kubernetes.io/Node' and row['evidence'].get('node_pool'):
            pools[row['evidence']['node_pool']].append(row)
    for members in pools.values():
        known=all(r['evidence']['requests'].get('complete') is True and all(type(r['evidence'].get('allocatable_'+d)) in (int,float) and r['evidence']['allocatable_'+d]>0 for d in ('cpu','memory')) for r in members)
        capacity={}
        if known:
            for dimension in ('cpu','memory'):
                capacity['allocatable_'+dimension]=sum(r['evidence']['allocatable_'+dimension] for r in members)
                capacity['requested_'+dimension]=sum(r['evidence']['requests'][dimension] for r in members)
                capacity['daemon_'+dimension]=sum(r['evidence']['requests']['daemon_'+dimension] for r in members)
        for row in members:row['evidence']['pool_capacity']=dict(capacity,complete=known,node_count=len(members))
    for parent in rows:
        if parent['resource_type']!='kubernetes.io/DaemonSet':continue
        e=parent['evidence'];containers=[r['evidence'] for r in rows if r['resource_type']=='kubernetes.io/Container' and (r['evidence'].get('controller') or {}).get('uid')==e['uid']]
        nodes={v.get('node') for v in containers};complete=bool(containers) and None not in nodes and len(nodes)==e.get('desired_replicas')
        slack=0.
        for c in containers:
            metrics=c.get('metrics') or {};cpu=metrics.get('cpu') or {};request=metrics.get('cpu_request') or {};throttle=metrics.get('throttling') or {};current=c.get('cpu_request')
            valid=all(v.get('sufficient') is True for v in (cpu,request,throttle)) and type(current) in (int,float) and request.get('minimum')==request.get('maximum')==current and throttle.get('p95',1)<=.02
            complete=complete and valid
            if valid:slack+=max(0,current-cpu['p95']*1.5)
        e['daemonset_allocation']=dict(complete=complete,cpu_slack_cores=slack if complete else None,observed_node_count=len(nodes))
    return rows
