"""Persist scan inventory rows into provider- and type-specific PostgreSQL tables."""
from __future__ import annotations

from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.typed_resources.azure_schemas import ALL_TYPED_TABLES, TYPE_TO_SPEC, extract_row_fields
from app.typed_resources.costs import load_resource_costs


def persist_typed_resource_row(db, workspace, scan_id, observed_at, observation, *, costs=None):
    """Upsert one typed-table row for a supported Azure resource type."""
    rtype = (observation.get('resource_type') or '').lower()
    spec = TYPE_TO_SPEC.get(rtype)
    if not spec:
        return None
    costs = costs or {}
    table = spec['table']
    fields = extract_row_fields(observation, spec)
    evidence = observation.get('evidence') or {}
    rid_key = observation['resource_id'].lower()
    parts = observation['resource_id'].split('/')
    group_index = next((i for i, part in enumerate(parts[:-1]) if part.lower() == 'resourcegroups'), None)
    resource_group = observation.get('resource_group') or (parts[group_index + 1] if group_index is not None else '')
    cost = costs.get(rid_key, costs.get(observation['resource_id'], {}))
    reporting_currency = cost.get('reporting_currency') or 'USD'
    columns = [
        'id', 'tenant_id', 'scan_id', 'resource_id', 'subscription_id', 'resource_group', 'name', 'location',
        'tags', 'observed_at', 'arm_api_version', 'provisioning_state',
        *fields.keys(),
        'reporting_currency', 'cost_period_start', 'cost_period_end',
        'azure_billed', 'azure_effective', 'azure_list',
        'cost_center_billed', 'cost_center_effective', 'cost_center_list',
        'azure_charge_count', 'cost_center_charge_count',
    ]
    values = [
        uuid4(),
        str(UUID(workspace['tenant_id'])),
        scan_id,
        observation['resource_id'],
        observation['subscription_id'],
        resource_group,
        observation.get('resource_name') or parts[-1],
        observation.get('region'),
        Jsonb(observation.get('evidence', {}).get('tags') or {}),
        observed_at,
        evidence.get('arm_api_version'),
        evidence.get('arm_provisioning_state') or fields.get('provisioning_state'),
        *fields.values(),
        cost.get('reporting_currency') or reporting_currency,
        cost.get('cost_period_start'),
        cost.get('cost_period_end'),
        cost.get('azure_billed'),
        cost.get('azure_effective'),
        cost.get('azure_list'),
        cost.get('cost_center_billed'),
        cost.get('cost_center_effective'),
        cost.get('cost_center_list'),
        cost.get('azure_charge_count', 0),
        cost.get('cost_center_charge_count', 0),
    ]
    placeholders = ','.join('%s' for _ in values)
    col_sql = ','.join(columns)
    db.execute(
        f'INSERT INTO public.{table} ({col_sql}) VALUES ({placeholders}) '
        f'ON CONFLICT (scan_id, resource_id) DO UPDATE SET '
        + ','.join(f'{c}=EXCLUDED.{c}' for c in columns if c not in ('id', 'tenant_id', 'scan_id', 'resource_id')),
        values,
    )
    return table


def persist_typed_resources(db, workspace, scan):
    inventory = scan.get('inventory') or []
    if not inventory:
        return {'tables': {}, 'reporting_currency': None}
    azure_rows = [row for row in inventory if row.get('cloud_provider', 'azure') == 'azure']
    resource_ids = [row['resource_id'] for row in azure_rows]
    currency, period_start, period_end, costs = load_resource_costs(db, workspace, scan, resource_ids)
    counts = {}
    for observation in azure_rows:
        rid_key = observation['resource_id'].lower()
        cost = dict(costs.get(rid_key, costs.get(observation['resource_id'], {})))
        cost['reporting_currency'] = currency
        cost['cost_period_start'] = period_start
        cost['cost_period_end'] = period_end
        merged_costs = {rid_key: cost, observation['resource_id']: cost}
        table = persist_typed_resource_row(
            db, workspace, scan['scan_id'], scan['timestamp'], observation, costs=merged_costs,
        )
        if table:
            counts[table] = counts.get(table, 0) + 1
    return {'tables': counts, 'reporting_currency': currency}


def list_tables():
    return [{'provider': s['provider'], 'resource_type': s.get('arm_type'), 'table': s['table']} for s in ALL_TYPED_TABLES]
