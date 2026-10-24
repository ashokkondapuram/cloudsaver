"""Tenant-bound service coverage, snapshot comparison and delegated rule previews."""
from collections import Counter
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.analysis_rules import RULES, evaluate_inventory, parameters
from app.auth import Role, require_workspace_role
from app.gitops_api import bounded_json
from app.inventory import coverage
from app.onboarding_api import _call

SERVICES = {'disks': 'disks', 'public-ips': 'publicipaddresses', 'virtual-machines': 'virtualmachines',
            'app-service-plans': 'serverfarms'}


class RuleChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    rule_id: str = Field(min_length=1, max_length=80)
    enabled: StrictBool
    parameters: dict[str, int] = Field(default_factory=dict)


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int = Field(ge=1)
    rules: list[RuleChange] = Field(min_length=1, max_length=100)


def create_router(store, current_tenant):
    router = APIRouter(prefix='/api/v1')

    def current_policy(tenant, authorization, *, management=False):
        path = (f'/customer/v1/workspaces/{tenant["tenant_id"]}/analysis-rules' if management else
                f'/internal/v1/tenants/{tenant["tenant_id"]}/analysis-rules/effective')
        return _call('GET', path, authorization=authorization)

    @router.get('/rules/effective')
    def effective(tenant=Depends(current_tenant), authorization: str = Header()):
        return current_policy(tenant, authorization)

    @router.put('/rules/overrides')
    def save(body: PolicyChange, tenant=Depends(current_tenant), authorization: str = Header()):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return _call('PUT', f'/customer/v1/workspaces/{tenant["tenant_id"]}/analysis-rules',
                     authorization=authorization, json=body.model_dump())

    @router.post('/rules/preview')
    def preview(body: PolicyChange, tenant=Depends(current_tenant), authorization: str = Header()):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        policy = current_policy(tenant, authorization, management=True)
        if body.version != policy['version']:
            raise HTTPException(409, 'Rule policy changed. Refresh before previewing again.')
        before = {row['id']: row for row in policy['items']}
        after = {key: dict(value) for key, value in before.items()}
        ids = [row.rule_id for row in body.rules]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, 'Include each rule only once.')
        for row in body.rules:
            if row.rule_id not in after or after[row.rule_id]['status'] != 'published':
                raise HTTPException(422, 'Choose a published rule.')
            try:
                if row.rule_id in {item[0] for item in RULES}:
                    parameters(row.rule_id, row.parameters)
                elif row.parameters:
                    raise ValueError('This rule has no delegated parameters.')
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            after[row.rule_id].update(enabled=row.enabled, parameters=row.parameters)
        scans = store.list(tenant['tenant_id'], 1)
        scan = scans[0] if scans else None
        changes = set()
        if scan and scan['status'] == 'completed':
            old = evaluate_inventory(scan.get('inventory', []), policies=before, observed_at=scan['timestamp'])
            new = evaluate_inventory(scan.get('inventory', []), policies=after, observed_at=scan['timestamp'])
            changes |= {a['resource_id'] for a, b in zip(old, new) if a['outcome'] != b['outcome']}
            changes |= {f['resource_id'] for f in scan['findings'] if f['rule_id'] in after
                        and before[f['rule_id']]['enabled'] != after[f['rule_id']]['enabled']}
        return dict(version=policy['version'], proposed=body.model_dump()['rules'],
                    scan_id=scan['scan_id'] if scan else None, resources_changed=len(changes) if scan else None,
                    message='Saved-observation preview only; no live cloud action or policy change was performed.')

    def selected(scan, service):
        suffix = SERVICES.get(service)
        if suffix is None:
            raise HTTPException(404, 'Service not found')
        return [row for row in scan.get('inventory', [])
                if row.get('cloud_provider', 'azure') == 'azure' and row['resource_type'].lower().endswith('/' + suffix)]

    @router.get('/services/{service}')
    def service_workspace(service: str, tenant=Depends(current_tenant)):
        if service not in SERVICES:
            raise HTTPException(404, 'Service not found')
        scans = [scan for scan in store.list(tenant['tenant_id'], 100) if scan['status'] == 'completed']
        trend = []
        current = []
        for index, scan in enumerate(scans):
            resources = selected(scan, service)
            ids = {r['resource_id'] for r in resources}
            outcomes = [r for r in scan.get('rule_evaluations', []) if r['resource_id'] in ids]
            findings = [r for r in scan['findings'] if r['resource_id'] in ids]
            item = dict(scan_id=scan['scan_id'], observed_at=scan['timestamp'],
                        coverage=coverage(resources, findings, outcomes), outcomes=dict(Counter(r['outcome'] for r in outcomes)),
                        opportunity_usd=None, verified_realized_savings_usd=None,
                        rule_matrix=[dict(rule_id=rule[0], name=rule[2],
                            outcomes=dict(Counter(r['outcome'] for r in outcomes if r['rule_id'] == rule[0])))
                            for rule in RULES if rule[1] == SERVICES[service]])
            trend.append(item)
            if index == 0:
                current = resources
        return dict(service=service, latest=trend[0] if trend else None, history=trend, resources=current)

    @router.get('/services/{service}/comparison')
    def compare(service: str, before: UUID, after: UUID, tenant=Depends(current_tenant)):
        scans = [store.get(tenant['tenant_id'], str(value)) for value in (before, after)]
        if any(scan is None for scan in scans):
            raise HTTPException(404, 'Scan not found')
        if any(scan['status'] != 'completed' for scan in scans):
            raise HTTPException(409, 'Comparison requires two completed observations.')
        def material(row):
            # Collection timestamps change on every run; they are not configuration changes.
            if 'configuration_snapshot' not in row:
                return {key: value for key, value in row.items() if key not in ('observed_at', 'timestamp')}
            return {key: row.get(key) for key in ('configuration_snapshot', 'protection_signals', 'region', 'resource_type',
                    'collector_version', 'evidence_schema_version')} | {'dependency_refs': [
                    {key: value for key, value in edge.items() if key != 'observed_at'} for edge in row.get('dependency_refs', [])]}
        rows = [{r['resource_id']: r for r in selected(scan, service)} for scan in scans]
        result = []
        for key in sorted(set(rows[0]) | set(rows[1])):
            state = ('new' if key not in rows[0] else 'no_longer_observed' if key not in rows[1]
                     else 'persisting' if material(rows[0][key]) == material(rows[1][key]) else 'changed')
            result.append(dict(resource_id=key, state=state))
        return dict(items=result, before=str(before), after=str(after), message='Observation change only; no deletion or savings is proven.')

    return router
