"""Bounded topology from authorized snapshot edges; no guessed dependencies or avoidable cash."""
from collections import defaultdict,deque
import hashlib
from app.assessment import protection


def identity(row):
    provider=row.get('cloud_provider','azure');rid=row['resource_id']
    return provider,rid.lower() if provider=='azure' else rid


def key_for(row):
    provider,rid=identity(row)
    return hashlib.sha256((provider+'|'+rid).encode()).hexdigest()


def graph(scan,root_key):
    rows={identity(row):row for row in scan.get('inventory',[])}
    key_to_id={key_for(row):key for key,row in rows.items()}
    if root_key not in key_to_id:return None
    neighbors=defaultdict(set);edges=[];seen=set()
    for key,row in rows.items():
        for edge in row.get('dependency_refs',[]):
            a_provider=edge.get('from_provider',key[0]);b_provider=edge.get('to_provider',key[0])
            a=(a_provider,edge['from_resource_id'].lower() if a_provider=='azure' else edge['from_resource_id'])
            b=(b_provider,edge['to_resource_id'].lower() if b_provider=='azure' else edge['to_resource_id'])
            edge_key=(a,b,edge['relationship'])
            if a not in rows or b not in rows or edge_key in seen:continue
            seen.add(edge_key);neighbors[a].add(b);neighbors[b].add(a)
            edges.append((a,b,edge))
    selected=set();pending=deque([key_to_id[root_key]])
    while pending:
        key=pending.popleft()
        if key in selected:continue
        if len(selected)>=200:raise ValueError('Dependency component exceeds 200 nodes; narrow the analysis scope.')
        selected.add(key);pending.extend(sorted(neighbors[key]-selected))
    return dict(scan_id=scan['scan_id'],observed_at=scan['timestamp'],root_key=root_key,
        nodes=[{'resource_key':key_for(rows[key]),'name':rows[key].get('resource_name'),'provider':key[0],
            'resource_type':rows[key]['resource_type'],'protected_reasons':protection(rows[key]),
            'reconciliation_status':rows[key].get('reconciliation_status','partial_telemetry'),'avoidable_monthly_cost_usd':None} for key in sorted(selected)],
        edges=[{'from_key':key_for(rows[a]),'to_key':key_for(rows[b]),'relationship':edge['relationship'],
            'verification_state':edge['verification_state'],'observed_at':edge.get('observed_at')} for a,b,edge in edges if a in selected and b in selected],
        verified_realized_savings_usd=None,
        warning='Only observed authorized endpoints are shown. Connectivity does not prove removability, complete dependencies, SLO safety or avoidable billed cost. Model financial assumptions separately.')
