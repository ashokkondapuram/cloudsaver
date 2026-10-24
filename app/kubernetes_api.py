"""Saved Kubernetes evidence and guarded review artifacts, with no live write endpoints."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import difflib
import hashlib
import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.auth import Role, require_workspace_role
from app.inventory import coverage
from app.k8s_cost_reconciler import breakdown
from app.kubernetes_rules import DEFINITIONS, evaluate_inventory
from app.collectors.provenance import digest


class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    resource_id:str=Field(min_length=1,max_length=2048)
    rule_id:str=Field(pattern=r'^K8S_CONTAINER_(CPU|MEMORY)_OVERREQUEST$')
    evidence_digest:str=Field(pattern=r'^[a-f0-9]{64}$')


def evidence_digest(row):
    return digest({'resource_id':row['resource_id'],'evidence':row.get('evidence'),
        'data_sources':row.get('data_sources'),'reconciliation_status':row.get('reconciliation_status')})


def workspace(scan):
    rows=[r for r in scan.get('inventory',[]) if r.get('cloud_provider')=='kubernetes']
    outcomes=[r for r in scan.get('rule_evaluations',[]) if r.get('cloud_provider')=='kubernetes']
    by_resource=defaultdict(list)
    for outcome in outcomes:by_resource[outcome['resource_id']].append(outcome)
    clusters=[]
    for cluster in sorted({r['scope_id'] for r in rows}):
        selected=[r for r in rows if r['scope_id']==cluster]
        ids={r['resource_id'] for r in selected}
        source_map={s['source_id']:s for r in selected for s in r.get('data_sources',[]) if isinstance(s,dict) and 'source_id' in s}
        source_map.update({s['source_id']:s for s in scan.get('source_ledger',[]) if s.get('provider')=='kubernetes' and s.get('scope_id')==cluster})
        nodes=[r for r in selected if r['resource_type']=='kubernetes.io/Node']
        capacity={}
        for dimension in ('cpu','memory'):
            known=bool(nodes) and all(type(r['evidence'].get('allocatable_'+dimension)) in (int,float) and r['evidence'].get('requests',{}).get('complete') is True for r in nodes)
            capacity[dimension]=dict(allocatable=sum(r['evidence']['allocatable_'+dimension] for r in nodes) if known else None,
                requested=sum(r['evidence']['requests'][dimension] for r in nodes) if known else None,
                daemonset=sum(r['evidence']['requests']['daemon_'+dimension] for r in nodes) if known else None,
                actual_p95=None,physical=None)
        clusters.append(dict(cluster_id=cluster,coverage=coverage(selected,[f for f in scan['findings'] if f['resource_id'] in ids],[r for r in outcomes if r['resource_id'] in ids]),
            sources=list(source_map.values()),capacity=capacity,
            reconciliation_status='source_conflict' if any(r.get('reconciliation_status')=='source_conflict' for r in selected) else 'partial_telemetry'))
    return dict(scan_id=scan['scan_id'],observed_at=scan['timestamp'],clusters=clusters,
        rule_matrix=[dict(rule_id=r[0],name=r[2],pillar=r[3],outcomes=dict(Counter(o['outcome'] for o in outcomes if o['rule_id']==r[0]))) for r in DEFINITIONS],
        resources=[dict(resource_id=r['resource_id'],resource_name=r['resource_name'],cluster_id=r['scope_id'],resource_type=r['resource_type'],
            namespace=r.get('evidence',{}).get('namespace'),evidence=r.get('evidence',{}),evidence_digest=evidence_digest(r),
            data_sources=r.get('data_sources',[]),reconciliation_status=r.get('reconciliation_status','partial_telemetry'),
            costs=breakdown(r),evaluations=by_resource[r['resource_id']]) for r in rows],
        financial_note='Container allocation opportunities are not additive to node consolidation or verified bill savings.')


def create_router(store,current_tenant):
    router=APIRouter(prefix='/api/v1/scans')
    def owned(scan_id,tenant):
        scan=store.get(tenant['tenant_id'],str(scan_id))
        if scan is None:raise HTTPException(404,'Scan not found')
        if scan['status']!='completed' or scan.get('data_origin')=='legacy_synthetic':
            raise HTTPException(409,'Kubernetes analysis requires a completed live observation')
        return scan

    @router.get('/{scan_id}/kubernetes')
    def view(scan_id:UUID,tenant=Depends(current_tenant)):
        return workspace(owned(scan_id,tenant))

    @router.post('/{scan_id}/kubernetes/patch-preview')
    def preview(scan_id:UUID,body:Preview,tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.TENANT_ADMIN)
        scan=owned(scan_id,tenant)
        resource=next((r for r in scan.get('inventory',[]) if r.get('cloud_provider')=='kubernetes' and r['resource_id']==body.resource_id),None)
        if resource is None:raise HTTPException(404,'Resource not found')
        from app.cloud_scope import validate_finding_scope
        try:
            validate_finding_scope(dict(resource,rule_id=body.rule_id),tenant)
        except (ValueError,KeyError):
            raise HTTPException(409,'This resource is outside the current workspace cluster scope.') from None
        if evidence_digest(resource)!=body.evidence_digest:raise HTTPException(409,'Evidence changed. Refresh before generating a review patch.')
        outcomes=evaluate_inventory([resource],policies=scan.get('rule_manifest',{}).get('policies'),observed_at=scan['timestamp'])
        outcome=next((r for r in outcomes if r['rule_id']==body.rule_id),None)
        if not outcome or outcome['outcome']!='condition_detected' or not outcome.get('recommendation') or outcome.get('safety_blocks') or outcome.get('protected_reasons'):
            raise HTTPException(409,'Required evidence or safety gates do not permit a request-change preview.')
        e=resource['evidence'];controller=e.get('controller') or {}
        if controller.get('kind') not in ('Deployment','StatefulSet','DaemonSet'):
            raise HTTPException(409,'A verified supported workload controller is required.')
        from app.cloud_scope import NAME, matches
        if not all(matches(NAME,e.get(k)) for k in ('namespace','container')) or not matches(NAME,controller.get('name')):
            raise HTTPException(409,'Controller identity is invalid for a review artifact.')
        # One pod cannot justify changing a controller with unverified sibling replicas.
        siblings=[r for r in scan.get('inventory',[]) if r.get('cloud_provider')=='kubernetes' and r.get('scope_id')==resource.get('scope_id') and r['resource_type']=='kubernetes.io/Container'
            and r.get('evidence',{}).get('namespace')==e['namespace'] and r.get('evidence',{}).get('controller')==controller and r.get('evidence',{}).get('container')==e['container']]
        proposals=[]
        controller_row=next((r for r in scan.get('inventory',[]) if r.get('cloud_provider')=='kubernetes' and r.get('scope_id')==resource.get('scope_id')
            and r['resource_type']=='kubernetes.io/'+controller['kind'] and r['resource_name']==controller['name']
            and r.get('evidence',{}).get('namespace')==e['namespace'] and r.get('evidence',{}).get('uid')==controller.get('uid')),None)
        desired=(controller_row or {}).get('evidence',{}).get('desired_replicas')
        if type(desired) is not int or desired<=0 or len({r['evidence'].get('pod') for r in siblings})!=desired:
            raise HTTPException(409,'Current desired replica count and the complete observed controller population must agree.')
        for sibling in siblings:
            candidate=next((r for r in evaluate_inventory([sibling],policies=scan.get('rule_manifest',{}).get('policies'),observed_at=scan['timestamp']) if r['rule_id']==body.rule_id),None)
            if not candidate or candidate['outcome']!='condition_detected' or not candidate.get('recommendation') or candidate.get('safety_blocks') or candidate.get('protected_reasons'):
                raise HTTPException(409,'Every observed replica must satisfy the same request-change evidence and safety gates.')
            proposals.append(candidate['recommendation'])
        dimension='cpu' if body.rule_id.endswith('CPU_OVERREQUEST') else 'memory'
        key='cpu_request_cores' if dimension=='cpu' else 'memory_request_bytes'
        import math
        amount=max(p[key] for p in proposals)
        rounded=math.ceil(amount*1000)/1000 if dimension=='cpu' else math.ceil(amount/1024**2)*1024**2
        if rounded>=min(r['evidence'][dimension+'_request'] for r in siblings):
            raise HTTPException(409,'A single safe lower request could not be established across all replicas.')
        target=str(math.ceil(amount*1000))+'m' if dimension=='cpu' else str(math.ceil(amount/1024**2))+'Mi'
        patch={'spec':{'template':{'spec':{'containers':[{'name':e['container'],'resources':{'requests':{dimension:target}}}]}}}}
        before=json.dumps({'resources':{'requests':{dimension:e.get(dimension+'_request')}}},indent=2).splitlines(True)
        after=json.dumps({'resources':{'requests':{dimension:target}}},indent=2).splitlines(True)
        filename=controller['name']+'.requests-review.patch.yaml'
        return dict(filename=filename,format='strategic-merge-patch',content=json.dumps(patch,indent=2)+'\n',
            diff=''.join(difflib.unified_diff(before,after,fromfile='saved-request',tofile='proposed-request')),
            evidence_digest=body.evidence_digest,replicas_reviewed=len(siblings),automatic_execution=False,
            review_commands=[f'kubectl --namespace {e["namespace"]} patch {controller["kind"].lower()} {controller["name"]} --type strategic --patch-file {filename} --dry-run=server -o yaml > proposed-workload.yaml',
                'kubectl diff -f proposed-workload.yaml'],
            warning='Review-only patch. No API write or GitOps submission was executed. Render against the current manifest, check limits/SLOs, and obtain change approval.')
    return router
