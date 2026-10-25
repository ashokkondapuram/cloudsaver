"""Connected service views and automatic, evidence-bounded planning inputs."""
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from app.resource_assessment import assessments, planning_summary

SERVICES={
    'disks':r'disk|volume','virtual-machines':r'virtualmachines|ec2:instance|compute.googleapis.com/instance',
    'public-ips':r'publicip|:eip|address|natgateway','app-service-plans':r'serverfarms|lambda|run.googleapis.com',
    'databases':r'rds|sql|cosmos|dynamodb|redis','load-balancers':r'loadbalanc|applicationgateway|forwardingrule',
    'object-storage':r'storageaccount|s3:bucket|storage.googleapis.com/bucket',
    'ai-endpoints':r'cognitive|bedrock|aiplatform|ai.endpoint'}


def create_router(store, current_tenant, finance):
    router=APIRouter(prefix='/api/v1')
    def owned(id,tenant):
        result=store.get(tenant['tenant_id'],str(id))
        if result is None:raise HTTPException(404,'Owned scan not found')
        if result.get('status')!='completed' or result.get('data_origin')=='legacy_synthetic':
            raise HTTPException(409,'A completed live scan is required')
        return finance.attach(tenant,result)

    @router.get('/services/{service}')
    def service_matrix(service:str,scan_id:UUID|None=None,tenant=Depends(current_tenant)):
        if service not in SERVICES:raise HTTPException(404,'Unknown service family')
        scans=store.list(tenant['tenant_id'],10)
        if not scans and scan_id is None:return dict(service=service,families=list(SERVICES),items=[],total=0,scan_id=None)
        scan=owned(scan_id or scans[0]['scan_id'],tenant)
        grouped=assessments(scan)
        items=[value[0] for value in grouped.values() if re.search(SERVICES[service],value[0]['resource_type'],re.I)]
        return dict(service=service,families=list(SERVICES),scan_id=scan['scan_id'],items=items[:1000],total=len(items),
                    history=[dict(scan_id=s['scan_id'],timestamp=s.get('timestamp')) for s in scans],
                    warning='Saved resource observations only. Unknown controls and missing billing are not proof of safety or savings.')

    @router.get('/optimization/scans/{scan_id}/auto-scenarios')
    def automatic_scenarios(scan_id:UUID,tenant=Depends(current_tenant)):
        scan=owned(scan_id,tenant)
        resources=[*scan.get('inventory',[]),*scan.get('findings',[])]
        dependencies=[];slo=[];network=[]
        visible_ids={r['resource_id'] for r in resources}
        for resource in resources:
            evidence=resource.get('evidence') or {}
            edges=evidence.get('verified_dependencies',[])
            safe_edges=[e for e in edges if isinstance(e,dict) and e.get('from_resource_id') in visible_ids and e.get('to_resource_id') in visible_ids] if isinstance(edges,list) else []
            if safe_edges:
                dependencies.append(dict(resource_id=resource['resource_id'],dependencies=safe_edges,
                                         inventory_complete=False))
            if isinstance(evidence.get('slo_burn_rate'),(int,float)):
                slo.append(dict(resource_id=resource['resource_id'],burn_rate=evidence['slo_burn_rate']))
            observed={k:evidence[k] for k in ('cross_az_traffic_gb','network_egress_gb','nat_bytes') if k in evidence}
            if observed:network.append(dict(resource_id=resource['resource_id'],observations=observed))
        return dict(scan_id=str(scan_id),automatic_execution=False,purchase_authorized=False,
            engines={'topology':dict(status='observed_edges' if dependencies else 'insufficient_evidence',items=dependencies[:1000],
                        blast_radius_verified=False),
                     'slo':dict(status='observed_signals' if slo else 'insufficient_evidence',items=slo[:1000],change_authorized=False),
                     'network':dict(status='observed_signals' if network else 'insufficient_evidence',items=network[:1000],savings_usd=None),
                     'commitment':planning_summary(dict(scan,commitment_evidence=None) if scan.get('provider_filtered') or scan.get('scope_filtered') else scan)},
            warning='Inputs come from the active scan and imported provider billing. Incomplete histories, graph coverage and rates remain unknown; no synthetic savings are generated.')
    return router
