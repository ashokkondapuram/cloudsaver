"""Workspace settings for tenant admins and tenant management for the platform operator.

Tenant admins edit only scopes that their own cloud grants protect (Azure
subscriptions in their directory, AWS roles that require their tenant ID as the
external ID, GCP projects reached through their operator-assigned service
account). Identity bindings and Kubernetes endpoints that reference
operator secrets are operator-only.
"""
import hashlib
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.auth import Role, operator_dependency, require_workspace_role

Tier = Literal['STARTER', 'GROWTH', 'ENTERPRISE']


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


class WorkspaceSettings(Strict):
    version: int = Field(ge=1)
    subscription_ids: list[UUID] = Field(max_length=100)
    aws_accounts: list[AwsAccount] = Field(max_length=100)
    gcp_projects: list[GcpProject] = Field(max_length=100)
    schedule: Schedule
    alerts: Alerts


class KubernetesCluster(Strict):
    cluster_id: str = Field(max_length=63)
    prometheus_url: str = Field(max_length=2048)
    bearer_token_env: str = Field(max_length=120)


class Identity(Strict):
    azure_app_client_id: UUID | None = None
    gcp_service_account: str | None = Field(None, max_length=120)


class TenantCreate(Strict):
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=120)
    plan_tier: Tier = 'STARTER'
    subscription_ids: list[UUID] = Field(default_factory=list, max_length=100)


class TenantPatch(Strict):
    version: int = Field(ge=1)
    name: str | None = Field(None, min_length=1, max_length=120)
    plan_tier: Tier | None = None
    active: StrictBool | None = None
    identity: Identity | None = None
    kubernetes_clusters: list[KubernetesCluster] | None = Field(None, max_length=100)


class PlatformPatch(Strict):
    version: int = Field(ge=0)
    scheduled_scans_enabled: StrictBool | None = None
    automated_alerts_enabled: StrictBool | None = None


def public_tenant(tenant):
    return {
        'tenant_id': tenant['tenant_id'], 'name': tenant['name'], 'plan_tier': tenant['plan_tier'],
        'active': tenant.get('active', True), 'version': tenant.get('version', 0),
        'subscription_ids': tenant['subscription_ids'], 'aws_accounts': tenant.get('aws_accounts', []),
        'gcp_projects': tenant.get('gcp_projects', []),
        'kubernetes_clusters': [{k: c[k] for k in ('cluster_id', 'prometheus_url', 'bearer_token_env')}
                                for c in tenant.get('kubernetes_clusters', [])],
        'identity': tenant.get('identity', {}), 'schedule': tenant.get('schedule', {}),
        'alerts': dict(tenant.get('alerts') or {'enabled': False, 'channel': None},
                       webhook_configured=bool(tenant.get('webhook_configured'))),
    }


def actor_for(workspace):
    principal = workspace.get('user_id') or 'workspace-key:' + workspace['tenant_id']
    return 'principal:' + hashlib.sha256(principal.encode()).hexdigest()


def create_router(settings, current_tenant):
    from app.cloud_identity import onboarding
    from app.entitlements import get_tier_entitlements
    from app.tenant_registry import UNSET, TenantExists, VersionConflict
    router = APIRouter()
    current_operator = operator_dependency()

    def registry():
        if settings.registry is None:
            raise HTTPException(503, 'Runtime settings require CLOUDSAVER_TENANT_REGISTRY=database')
        return settings.registry

    def save(call):
        try:
            return call()
        except VersionConflict:
            raise HTTPException(409, 'Settings changed since you loaded them. Refresh and try again.') from None
        except TenantExists as exc:
            raise HTTPException(409, str(exc)) from None
        except KeyError:
            raise HTTPException(404, 'Tenant not found') from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    def limits(tier):
        plan = get_tier_entitlements(tier)
        return {'max_subscriptions': plan.max_subscriptions, 'allowed_scan_frequencies': plan.allowed_scan_frequencies,
                'can_dispatch_automated_alerts': plan.can_dispatch_automated_alerts}

    @router.get('/api/v1/settings')
    def read_settings(workspace=Depends(current_tenant)):
        stored = settings.registry.get(workspace['tenant_id']) if settings.registry is not None else None
        platform = settings.registry.platform() if settings.registry is not None else None
        return {'editable': settings.registry is not None and Role.TENANT_ADMIN.value in workspace.get('roles', []),
                'settings': public_tenant(stored or workspace), 'limits': limits(workspace['plan_tier']),
                'platform': platform, 'identity': onboarding(stored or workspace)}

    @router.put('/api/v1/settings')
    def write_settings(payload: WorkspaceSettings, workspace=Depends(current_tenant)):
        require_workspace_role(workspace, Role.TENANT_ADMIN)
        store = registry()
        plan = get_tier_entitlements(workspace['plan_tier'])
        if len(payload.subscription_ids) > plan.max_subscriptions:
            raise HTTPException(402, f'Your plan allows up to {plan.max_subscriptions} Azure subscriptions.')
        if payload.schedule.frequency not in plan.allowed_scan_frequencies:
            raise HTTPException(402, f'Your plan does not include {payload.schedule.frequency} scans.')
        if payload.alerts.enabled and not plan.can_dispatch_automated_alerts:
            raise HTTPException(402, 'Your plan does not include automated alerts.')
        current = store.get(workspace['tenant_id'])
        if current is None:
            raise HTTPException(404, 'Tenant not found')
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
        changes = {
            'subscription_ids': [str(s) for s in payload.subscription_ids],
            'aws_accounts': [a.model_dump() for a in payload.aws_accounts],
            'gcp_projects': [p.model_dump() for p in payload.gcp_projects],
            'schedule': payload.schedule.model_dump(),
            'alerts': {'enabled': alerts.enabled, 'channel': alerts.channel},
        }
        tenant = save(lambda: store.update(workspace['tenant_id'], changes, payload.version, actor_for(workspace), webhook=webhook))
        return {'settings': public_tenant(tenant)}

    @router.get('/api/v1/admin/tenants')
    def list_tenants(operator=Depends(current_operator)):
        store = registry()
        return {'tenants': [public_tenant(t) for t in store.all()], 'platform': store.platform(),
                'identity': onboarding()}

    @router.post('/api/v1/admin/tenants', status_code=201)
    def create_tenant(payload: TenantCreate, operator=Depends(current_operator)):
        store = registry()
        plan = get_tier_entitlements(payload.plan_tier)
        if len(payload.subscription_ids) > plan.max_subscriptions:
            raise HTTPException(402, f'The {payload.plan_tier.title()} plan allows up to {plan.max_subscriptions} Azure subscriptions.')
        key = secrets.token_urlsafe(32)
        raw = dict(tenant_id=str(payload.tenant_id), name=payload.name, plan_tier=payload.plan_tier,
                   subscription_ids=[str(s) for s in payload.subscription_ids],
                   api_key_sha256=hashlib.sha256(key.encode()).hexdigest())
        tenant = save(lambda: store.create(raw, operator['actor']))
        return {'tenant': public_tenant(tenant), 'workspace_key': key}

    @router.patch('/api/v1/admin/tenants/{tenant_id}')
    def update_tenant(tenant_id: UUID, payload: TenantPatch, operator=Depends(current_operator)):
        store = registry()
        changes = payload.model_dump(exclude_none=True, exclude={'version', 'identity', 'kubernetes_clusters'})
        if payload.identity is not None:
            changes['identity'] = {k: str(v) for k, v in payload.identity.model_dump(exclude_none=True).items()}
        if payload.kubernetes_clusters is not None:
            changes['kubernetes_clusters'] = [c.model_dump() for c in payload.kubernetes_clusters]
        tenant = save(lambda: store.update(str(tenant_id), changes, payload.version, operator['actor']))
        return {'tenant': public_tenant(tenant)}

    @router.get('/api/v1/admin/settings')
    def read_platform(operator=Depends(current_operator)):
        return {'platform': registry().platform(), 'identity': onboarding()}

    @router.put('/api/v1/admin/settings')
    def write_platform(payload: PlatformPatch, operator=Depends(current_operator)):
        store = registry()
        changes = payload.model_dump(exclude_none=True, exclude={'version'})
        return {'platform': save(lambda: store.update_platform(changes, payload.version, operator['actor']))}

    return router
