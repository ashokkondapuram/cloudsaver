"""Exact observed cloud/cluster links. Missing cloud nodes never become inferred topology."""
from app.k8s_cost_reconciler import cloud_identity


def link(rows,observed_at):
    def identity(row):
        provider=row.get('cloud_provider','azure')
        return provider,row['resource_id'].lower() if provider=='azure' else row['resource_id']
    by_id={identity(row):row for row in rows}
    def edge(row,target,relation):
        value=dict(relationship=relation,from_resource_id=row['resource_id'],to_resource_id=target['resource_id'],
                   from_provider=row.get('cloud_provider','azure'),to_provider=target.get('cloud_provider','azure'),
                   verification_state='verified',observed_at=observed_at)
        if value not in row.setdefault('dependency_refs',[]):row['dependency_refs'].append(value)
    for row in rows:
        if row.get('cloud_provider')!='kubernetes':continue
        evidence=row.get('evidence') or {};kind=row['resource_type'].split('/')[-1]
        if kind=='Node':
            key=cloud_identity(evidence.get('provider_id'))
            if key in by_id:edge(row,by_id[key],'k8s_node_to_cloud_vm')
        if kind=='PersistentVolume':
            handle=evidence.get('csi_volume_handle')
            target=by_id.get(('azure',handle.lower())) if isinstance(handle,str) and handle.startswith('/subscriptions/') else None
            if target:edge(row,target,'pvc_to_pv_to_cloud_disk')
        if kind=='PersistentVolumeClaim':
            volume=evidence.get('volume_name')
            target=by_id.get(('kubernetes',f'k8s://{row["scope_id"]}/persistentvolumes/{volume}'))
            if target:
                edge(row,target,'pvc_to_pv_to_cloud_disk')
                handle=target.get('evidence',{}).get('csi_volume_handle')
                disk=by_id.get(('azure',handle.lower())) if isinstance(handle,str) else None
                if disk and evidence.get('phase')=='Bound' and disk.get('evidence',{}).get('disk_state')=='Unattached':
                    for affected in (row,target,disk):
                        affected['reconciliation_status']='source_conflict'
                        affected.setdefault('reconciliation_warnings',[]).append('BOUND_PVC_WITH_UNATTACHED_CLOUD_DISK')
