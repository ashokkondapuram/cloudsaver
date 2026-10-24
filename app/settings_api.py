"""Workspace settings for tenant admins.

Tenant admins edit scopes that their own cloud grants protect (Azure
subscriptions in their directory, AWS roles that require their tenant ID as the
external ID, GCP projects reached through their operator-assigned service
account) and their own resource-access identity bindings (Azure app client ID,
GCP service account). Kubernetes endpoints that reference operator secrets
remain managed by platform operators in the platform portal. In directory
cutover mode all of the above are projected from the platform and read-only here.
"""
import hashlib
from typing import Literal
from uuid import UUID

from fastapi import Header, APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.auth import Role, require_workspace_role
from app.config import directory_mode
from app.provider_access import narrow
from app.tenant_config import normalize_identity
from app.foundry_config import FoundrySettings

SCOPES_IN_PORTAL = 'Cloud accounts are managed in the platform portal. Contact your CloudSaver administrator to change them.'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AwsAccount(Strict):
    account_id: str = Field(max_length=12)
    region: str = Field(max_length=40)
    role_arn: str = Field(max_length=600)


class GcpProject(Strict):
    project_id: str = Field(max_length=30)
    regions: list[str] = Field(min_length=1, max_length=50)


class Schedule(Strict):
    frequency: Literal['manual', 'daily', 'hourly']


class Alerts(Strict):
    enabled: StrictBool
    channel: Literal['slack', 'teams'] | None = None
    webhook_url: str | None = Field(None, max_length=4096)
    remove_webhook: StrictBool = False


class PlanChange(Strict):
    version: int = Field(ge=1)
    plan_tier: Literal['STARTER', 'GROWTH', 'ENTERPRISE']


class Identity(Strict):
    azure_app_client_id: str | None = Field(None, max_length=64)
    gcp_service_account: str | None = Field(None, max_length=320)


class WorkspaceSettings(Strict):
    version: int = Field(ge=1)
    subscription_ids: list[UUID] = Field(max_length=100)
    aws_accounts: list[AwsAccount] = Field(max_length=100)
    gcp_projects: list[GcpProject] = Field(max_length=100)
    schedule: Schedule
    alerts: Alerts
    identity: Identity | None = None
    ai_foundry: FoundrySettings | None = None
    acknowledge_external_processing: StrictBool = False


def public_tenant(tenant):
    return {
        'tenant_id': tenant['tenant_id'], 'name': tenant['name'], 'plan_tier': tenant['plan_tier'],
        'active': tenant.get('active', True), 'version': tenant.get('version', 0),
        'subscription_ids': tenant['subscription_ids'], 'aws_accounts': tenant.get('aws_accounts', []),
        'gcp_projects': tenant.get('gcp_projects', []),
        'kubernetes_clusters': [{k: c[k] for k in ('cluster_id', 'prometheus_url', 'bearer_token_env')}
                                for c in tenant.get('kubernetes_clusters', [])],
        'identity': tenant.get('identity', {}), 'schedule': tenant.get('schedule', {}),
        'ai_foundry': tenant.get('ai_foundry'),
        'alerts': dict(tenant.get('alerts') or {'enabled': False, 'channel': None},
                       webhook_configured=bool(tenant.get('webhook_configured'))),
    }


def actor_for(workspace):
    principal = workspace.get('subject_id') or workspace.get('user_id') or 'workspace-key:' + (workspace.get('key_id') or workspace['tenant_id'])
    return 'principal:' + hashlib.sha256(principal.encode()).hexdigest()


def create_router(settings, current_tenant, identity_client=None, scan_store=None):
    from app.cloud_identity import onboarding
    from app.entitlements import (enforce_automated_alerts, enforce_providers, enforce_scan_frequency,
                                  enforce_subscription_quota, entitlements_for)
    from app.tenant_registry import UNSET, VersionConflict
    router = APIRouter()

    def registry():
        if settings.registry is None:
            raise HTTPException(503, 'Runtime settings require CLOUDSAVER_TENANT_REGISTRY=database')
        return settings.registry

    def identity():
        if identity_client is not None:
            return identity_client
        from app.identity_client import shared_client
        return shared_client()

    def save(call):
        try:
            return call()
        except VersionConflict:
            raise HTTPException(409, 'Settings changed since you loaded them. Refresh and try again.') from None
        except KeyError:
            raise HTTPException(404, 'Workspace not found') from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    def limits(workspace):
        plan = entitlements_for(workspace)
        return {'max_subscriptions': plan.max_subscriptions, 'allowed_scan_frequencies': plan.allowed_scan_frequencies,
                'can_dispatch_automated_alerts': plan.can_dispatch_automated_alerts,
                'allowed_providers': plan.allowed_providers}

    def cutover():
        return directory_mode() == 'cutover'

    def visible(stored, workspace):
        allowed = workspace.get('allowed_providers')
        return narrow(stored, allowed) if stored is not None and allowed is not None else stored

    @router.get('/api/v1/settings')
    def read_settings(workspace=Depends(current_tenant)):
        stored = visible(settings.registry.get(workspace['tenant_id']) if settings.registry is not None else None, workspace)
        platform = settings.registry.platform() if settings.registry is not None else None
        editable = settings.registry is not None and Role.TENANT_ADMIN.value in workspace.get('roles', [])
        return {'editable': editable, 'scopes_editable': editable and not cutover(), 'directory_mode': directory_mode(),
                'settings': public_tenant(stored or workspace), 'limits': limits(workspace),
                'platform': platform, 'identity': onboarding(stored or workspace, platform)}

    @router.put('/api/v1/settings')
    def write_settings(payload: WorkspaceSettings, workspace=Depends(current_tenant)):
        require_workspace_role(workspace, Role.TENANT_ADMIN)
        store = registry()
        plan = entitlements_for(workspace)
        current = store.get(workspace['tenant_id'])
        if current is None:
            raise HTTPException(404, 'Workspace not found')
        enforce_scan_frequency(plan, payload.schedule.frequency)
        if payload.alerts.enabled:
            enforce_automated_alerts(plan)
        alerts = payload.alerts
        webhook = UNSET
        if alerts.remove_webhook:
            webhook = None
        elif alerts.webhook_url:
            from app.delivery_config import validate_webhook
            try:
                webhook = validate_webhook(alerts.webhook_url, alerts.channel)
            except (ValueError, TypeError):
                raise HTTPException(422, 'Enter an HTTPS Slack or Teams webhook URL that matches the channel.') from None
        keeps_webhook = isinstance(webhook, str) or (webhook is UNSET and bool(current.get('webhook_configured')))
        if webhook is UNSET and current.get('webhook_configured') and alerts.channel != current['alerts']['channel']:
            raise HTTPException(422, 'Enter the webhook URL for the new channel.')
        if alerts.enabled and not keeps_webhook:
            raise HTTPException(422, 'Add a webhook URL before you turn on alerts.')
        identity_changes = {}
        if payload.identity is not None:
            try:
                new_identity = normalize_identity(payload.identity.model_dump())
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            if new_identity != (current.get('identity') or {}):
                if cutover():
                    raise HTTPException(403, SCOPES_IN_PORTAL)
                identity_changes = {'identity': new_identity}
        scopes = {
            'subscription_ids': [str(s) for s in payload.subscription_ids],
            'aws_accounts': [a.model_dump() for a in payload.aws_accounts],
            'gcp_projects': [p.model_dump() for p in payload.gcp_projects],
        }
        allowed = workspace.get('allowed_providers')
        shown = visible(current, workspace)
        if cutover():
            if any(scopes[k] != shown.get(k, []) for k in scopes):
                raise HTTPException(403, SCOPES_IN_PORTAL)
            scopes = {}
        elif allowed is not None:
            # Scopes of providers outside the key are preserved and never shown.
            provider_of = {'subscription_ids': 'azure', 'aws_accounts': 'aws', 'gcp_projects': 'gcp'}
            scopes = {k: (v if provider_of[k] in allowed else current.get(k, [])) for k, v in scopes.items()}
        if scopes:
            provider_of = {'subscription_ids': 'azure', 'aws_accounts': 'aws', 'gcp_projects': 'gcp'}
            enforce_providers(plan, [provider_of[k] for k, v in scopes.items() if v and v != current.get(k, [])])
            total = sum(len(v) for v in scopes.values())
            # A downgraded workspace can still edit its schedule or remove scopes; it just can't add more.
            if total > sum(len(current.get(k, [])) for k in scopes):
                enforce_subscription_quota(plan, total + len(current.get('kubernetes_clusters', [])), adding_count=0)
        changes = dict(scopes, **identity_changes, schedule=payload.schedule.model_dump(),
                       alerts={'enabled': alerts.enabled, 'channel': alerts.channel})
        if payload.ai_foundry is not None:
            from app.foundry import FoundryController
            from app.ai_advisory import AIError
            try:
                controller = FoundryController(settings)
                controller.check_write(workspace, payload.ai_foundry.model_dump(), payload.acknowledge_external_processing)
                changes['ai_foundry'] = controller.validate_configuration(workspace, payload.ai_foundry.model_dump())
            except AIError as error:
                raise HTTPException(error.status, str(error)) from None
        tenant = save(lambda: store.update(workspace['tenant_id'], changes, payload.version, actor_for(workspace), webhook=webhook))
        return {'settings': public_tenant(visible(tenant, workspace))}

    @router.get('/api/v1/billing/plans')
    def billing_plans(workspace=Depends(current_tenant)):
        require_workspace_role(workspace, Role.BILLING_ADMIN)
        from app.billing_plan import list_plans, pending_plan_change_request
        from app.identity_client import IdentityUnavailable
        pending = None
        try:
            pending = pending_plan_change_request(identity(), workspace['tenant_id'])
        except IdentityUnavailable:
            pass
        return {'items': list_plans(), 'current_tier': entitlements_for(workspace).tier, 'pending_request': pending}

    @router.get('/api/v1/billing/plan-requests')
    def billing_plan_request_status(workspace=Depends(current_tenant)):
        require_workspace_role(workspace, Role.BILLING_ADMIN)
        from app.billing_plan import pending_plan_change_request
        from app.identity_client import IdentityUnavailable
        try:
            pending = pending_plan_change_request(identity(), workspace['tenant_id'])
        except IdentityUnavailable:
            raise HTTPException(503, 'Plan requests are unavailable. Try again later.')
        return pending or {}

    @router.post('/api/v1/billing/plan-requests', status_code=202)
    def billing_plan_request(payload: PlanChange, workspace=Depends(current_tenant)):
        require_workspace_role(workspace, Role.BILLING_ADMIN)
        if not workspace.get('customer_id'):
            raise HTTPException(422, 'This workspace is not linked to a platform customer. Contact your CloudSaver administrator.')
        from app.billing_plan import submit_plan_change_request
        from app.identity_client import IdentityUnavailable
        actor = actor_for(workspace)
        try:
            request = submit_plan_change_request(identity(), workspace['tenant_id'], payload.plan_tier, actor)
        except IdentityUnavailable:
            raise HTTPException(503, 'Plan requests are unavailable. Try again later.')
        except ValueError as exc:
            raise HTTPException(409 if 'pending' in str(exc).lower() else 422, str(exc)) from None
        return request

    @router.post('/api/v1/settings/access-test')
    def access_test(workspace=Depends(current_tenant)):
        require_workspace_role(workspace, Role.TENANT_ADMIN)
        store = registry()
        tenant = store.get(workspace['tenant_id']) or workspace
        key = f'access-test:{workspace["tenant_id"]}'
        if not hasattr(access_test, '_limits'):
            access_test._limits = {}
        import time
        now = time.monotonic()
        window = [t for t in access_test._limits.get(key, []) if now - t < 60]
        if len(window) >= 3:
            raise HTTPException(429, 'Too many access tests. Try again in a minute.')
        window.append(now)
        access_test._limits[key] = window
        from app.access_probe import run_probe
        return run_probe(tenant, store.platform())

    def current_policy(tenant, authorization, *, management=False):
        path = (f'/customer/v1/workspaces/{tenant["tenant_id"]}/analysis-rules' if management else
                f'/internal/v1/tenants/{tenant["tenant_id"]}/analysis-rules/effective')
        return _call('GET', path, authorization=authorization)

    @router.get('/api/v1/rules/effective')
    def effective(tenant=Depends(current_tenant), authorization: str = Header()):
        return current_policy(tenant, authorization)

    @router.put('/api/v1/rules/overrides')
    def save_rules(body: PolicyChange, tenant=Depends(current_tenant), authorization: str = Header()):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return _call('PUT', f'/customer/v1/workspaces/{tenant["tenant_id"]}/analysis-rules',
                     authorization=authorization, json=body.model_dump())

    @router.post('/api/v1/rules/preview')
    def preview_rules(body: PolicyChange, tenant=Depends(current_tenant), authorization: str = Header()):
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
                else:
                    from app.resource_catalog import definitions
                    bounds={r[0]:r[6] for r in definitions()}.get(row.rule_id,{})
                    if set(row.parameters)-set(bounds) or any(type(v) is not int or not bounds[k][1]<=v<=bounds[k][2] for k,v in row.parameters.items()):
                        raise ValueError('Rule parameters are outside published delegated bounds.')
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            after[row.rule_id].update(enabled=row.enabled, parameters=row.parameters)
        scans = scan_store.list(tenant['tenant_id'], 1)
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

    return router


from app.analysis_rules import RULES, evaluate_inventory, parameters
from app.onboarding_api import _call

class RuleChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    rule_id: str = Field(min_length=1, max_length=80)
    enabled: StrictBool
    parameters: dict[str, int] = Field(default_factory=dict)


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int = Field(ge=1)
    rules: list[RuleChange] = Field(min_length=1, max_length=100)
