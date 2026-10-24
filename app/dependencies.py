"""Typed, observed relationships; inferred and stale links never establish savings groups."""
from collections import defaultdict
import hashlib
from datetime import datetime, timezone

from app.assessment import category, protection
from app.telemetry_contract import moment

RELATIONSHIPS = {'vm_to_disk', 'vm_to_nic', 'nic_to_ip', 'ip_to_load_balancer_or_nat_or_appgw',
                 'app_service_to_plan', 'resource_to_backup_vault_or_asr', 'resource_to_management_lock',
                 'pvc_to_pv_to_cloud_disk', 'k8s_service_to_cloud_lb', 'k8s_node_to_cloud_vm'}


def identity(row):
    provider = row.get('cloud_provider', 'azure')
    key = row['resource_id'].lower() if provider == 'azure' else row['resource_id']
    return provider, key


def canonical_inventory(rows, observed_at):
    result = {}
    for original in rows:
        row = dict(original)
        key = identity(row)
        evidence = row.get('evidence') or {}
        if not isinstance(evidence, dict):
            raise ValueError('Invalid inventory configuration evidence')
        edges = []
        for edge in row.get('dependency_refs', []):
            if (not isinstance(edge, dict) or edge.get('relationship') not in RELATIONSHIPS
                    or edge.get('verification_state') not in ('verified', 'inferred', 'stale', 'unavailable')
                    or not isinstance(edge.get('from_resource_id'), str) or not isinstance(edge.get('to_resource_id'), str)):
                raise ValueError('Invalid typed dependency evidence')
            stamp = moment(edge.get('observed_at'))
            current = moment(observed_at)
            state = edge['verification_state']
            if state == 'verified' and (not stamp or not current or not 0 <= (current - stamp).total_seconds() < 86400):
                state = 'stale'
            edges.append({k: edge[k] for k in ('relationship', 'from_resource_id', 'to_resource_id')} |
                         {k:edge[k] for k in ('from_provider','to_provider') if k in edge} |
                         {'verification_state': state, 'observed_at': edge.get('observed_at')})
        row.update(provider=key[0], service=category(row), scope_id=row.get('scope_id') or row.get('subscription_id'),
            region=row.get('region'), configuration_snapshot={k: v for k, v in evidence.items() if k not in ('metrics', 'state_history')},
            protection_signals=protection(row), dependency_refs=edges, observed_at=observed_at,
            collector_version=row.get('collector_version', 'legacy-unspecified'), evidence_schema_version='2')
        if key in result and result[key] != row:
            raise ValueError('Conflicting observations for one canonical resource')
        result[key] = row
    from app.collectors.reconciliation import link
    link(list(result.values()),observed_at)
    # Only disclose graph nodes present in the authorized observation. No unobserved parent topology is invented.
    for row in result.values():
        row['protection_signals']=protection(row)
        provider = row.get('cloud_provider', 'azure')
        normalize = lambda value: value.lower() if provider == 'azure' else value
        row['dependency_refs'] = [edge for edge in row['dependency_refs']
            if (edge.get('from_provider',provider), edge['from_resource_id'].lower() if edge.get('from_provider',provider)=='azure' else edge['from_resource_id']) in result
            and (edge.get('to_provider',provider), edge['to_resource_id'].lower() if edge.get('to_provider',provider)=='azure' else edge['to_resource_id']) in result]
    return list(result.values())


def group_opportunities(findings, inventory):
    nodes = {identity(row): row for row in inventory}
    adjacency = defaultdict(set)
    for row in inventory:
        provider = row.get('cloud_provider', 'azure')
        if provider != 'azure':
            continue
        for edge in row.get('dependency_refs', []):
            if edge['verification_state'] != 'verified' or edge['relationship'] not in ('vm_to_disk', 'vm_to_nic', 'nic_to_ip'):
                continue
            a, b = (provider, edge['from_resource_id'].lower()), (provider, edge['to_resource_id'].lower())
            if a in nodes and b in nodes:
                adjacency[a].add(b)
                adjacency[b].add(a)
    groups, visited = {}, set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        component, pending = set(), [start]
        while pending:
            key = pending.pop()
            if key in component:
                continue
            component.add(key)
            pending.extend(adjacency[key] - component)
        visited |= component
        parents = [key for key in component if nodes[key]['resource_type'].lower() == 'microsoft.compute/virtualmachines']
        if len(parents) == 1:
            for key in component:
                groups[key] = 'workload:' + hashlib.sha256((parents[0][0] + '|' + parents[0][1]).encode()).hexdigest()
    findings = [dict(row, opportunity_group_id=groups[identity(row)], opportunity_overlap_basis='verified_observed_relationships')
            if row.get('resource_id') and identity(row) in groups else row for row in findings]
    from app.k8s_cost_reconciler import group_opportunities as group_kubernetes
    return group_kubernetes(findings, inventory)
