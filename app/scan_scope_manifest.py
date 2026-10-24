"""Explicit successful inventory scope contracts, including scopes that returned zero resources."""
TYPES={
    'azure':['microsoft.compute/disks','microsoft.compute/virtualmachines','microsoft.network/publicipaddresses',
             'microsoft.web/serverfarms','microsoft.network/networkinterfaces','microsoft.network/networksecuritygroups','microsoft.network/applicationgateways'],
    'aws':['aws:ec2:volume','aws:ec2:elastic-ip','aws:rds:db'],
    'gcp':['compute.googleapis.com/Disk','compute.googleapis.com/Address','sqladmin.googleapis.com/Instance'],
}


def completed_scopes(tenant,providers,source_ledger):
    scopes={'azure':tenant.get('subscription_ids',[]),'aws':[s['account_id'] for s in tenant.get('aws_accounts',[])],
        'gcp':[s['project_id'] for s in tenant.get('gcp_projects',[])],'kubernetes':[s['cluster_id'] for s in tenant.get('kubernetes_clusters',[])]}
    results=[]
    for provider in sorted(providers):
        for scope in sorted(set(scopes[provider])):
            kinds=TYPES.get(provider,[])
            complete=True
            if provider=='kubernetes':
                kinds=['kubernetes.io/'+s['source_id'].split(':',1)[1] for s in source_ledger
                       if s.get('provider')==provider and s.get('scope_id')==scope and s.get('status')=='available' and s.get('source_id','').startswith('kubernetes_api:')]
                if 'kubernetes.io/Pod' in kinds:kinds.append('kubernetes.io/Container')
                complete=bool(kinds)
            results.append(dict(provider=provider,scope_id=scope,status='completed',supported_inventory_complete=complete,
                supported_resource_types=kinds,basis='configured_supported_type_collectors',
                regions=sorted({r['region'] for r in tenant.get('aws_accounts',[]) if r['account_id']==scope}) if provider=='aws'
                    else sorted({region for r in tenant.get('gcp_projects',[]) if r['project_id']==scope for region in r['regions']}) if provider=='gcp' else None))
    return results
