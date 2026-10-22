"""Verify Entra v2 delegated access tokens before deriving workspace roles."""
import hashlib
import hmac
import os
from enum import Enum
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field


class Role(str, Enum):
    TENANT_ADMIN = 'TenantAdmin'
    VIEWER = 'Viewer'
    BILLING_ADMIN = 'BillingAdmin'


class UserClaims(BaseModel):
    user_id: str
    tenant_id: str
    roles: list[Role] = Field(default_factory=list)
    email: str | None = None
    name: str | None = None
    raw_claims: dict[str, Any] = Field(default_factory=dict)

    def has_role(self, role):
        return Role.TENANT_ADMIN in self.roles or role in self.roles or (role == Role.VIEWER and bool(self.roles))


class EntraIdConfig(BaseModel):
    client_id: str = Field(default_factory=lambda: os.getenv('CLOUDSAVER_ENTRA_AUDIENCE', ''))
    allowed_tenants: set[str] = Field(default_factory=set)
    required_scope: str = 'access_as_user'


@lru_cache(maxsize=128)
def jwks_client(tenant_id):
    return jwt.PyJWKClient(f'https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys',
                           cache_jwk_set=True, lifespan=3600, timeout=5)


class EntraTokenValidator:
    def __init__(self, config=None, *, key_resolver=None):
        self.config = config or EntraIdConfig()
        self.key_resolver = key_resolver

    def verify_token(self, token, expected_tenant_id=None):
        if not self.config.client_id or not self.config.allowed_tenants:
            raise HTTPException(503, 'Entra audience and authorized tenants must be configured')
        if not isinstance(token, str) or len(token) > 16384:
            raise HTTPException(401, 'Invalid Entra access token')
        try:
            unverified = jwt.decode(token, options={'verify_signature': False})
            tenant_id = str(UUID(unverified['tid']))
            if tenant_id not in self.config.allowed_tenants:
                raise HTTPException(403, 'Workspace is not authorized')
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str) or not header['kid']:
                raise jwt.InvalidTokenError()
            key = (self.key_resolver(tenant_id, token) if self.key_resolver
                   else jwks_client(tenant_id).get_signing_key_from_jwt(token).key)
            claims = jwt.decode(token, key, algorithms=['RS256'], audience=self.config.client_id,
                                issuer=f'https://login.microsoftonline.com/{tenant_id}/v2.0',
                                options={'require': ['exp', 'nbf', 'iat', 'iss', 'aud', 'tid', 'oid', 'sub', 'ver', 'scp']})
            if claims['ver'] != '2.0' or claims['tid'] != tenant_id or claims['aud'] != self.config.client_id:
                raise jwt.InvalidTokenError()
            if not isinstance(claims['scp'], str) or self.config.required_scope not in claims['scp'].split():
                raise HTTPException(403, 'CloudSaver delegated access scope is required')
            user_id = str(UUID(claims['oid']))
            if expected_tenant_id and tenant_id != str(UUID(expected_tenant_id)):
                raise HTTPException(403, 'Token tenant does not match the requested workspace')
            raw_roles = claims.get('roles', [])
            if not isinstance(raw_roles, list) or not all(isinstance(r, str) for r in raw_roles):
                raise jwt.InvalidTokenError()
            roles = [Role(r) for r in raw_roles if r in Role._value2member_map_]
            if not roles:
                raise HTTPException(403, 'An assigned CloudSaver application role is required')
            return UserClaims(user_id=user_id, tenant_id=tenant_id, roles=roles,
                              email=claims.get('preferred_username'), name=claims.get('name'), raw_claims=claims)
        except HTTPException:
            raise
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503, 'Entra signing keys are temporarily unavailable') from None
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(401, 'Invalid Entra access token', headers={'WWW-Authenticate': 'Bearer'}) from None


def require_workspace_role(workspace, role):
    roles = workspace.get('roles', [])
    if Role.TENANT_ADMIN.value not in roles and role.value not in roles:
        raise HTTPException(403, f'{role.value} role is required')


def tenant_dependency(settings, validator=None):
    mode = os.getenv('CLOUDSAVER_AUTH_MODE', 'workspace')
    if mode not in ('workspace', 'entra'):
        raise ValueError('CLOUDSAVER_AUTH_MODE must be workspace or entra')
    validator = validator or EntraTokenValidator(EntraIdConfig(allowed_tenants={t['tenant_id'] for t in settings.tenants}))
    bearer = HTTPBearer(auto_error=False)

    def current(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or credentials.scheme.lower() != 'bearer':
            raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
        if mode == 'entra':
            claims = validator.verify_token(credentials.credentials)
            matched = next((t for t in settings.tenants if t['tenant_id'] == claims.tenant_id), None)
            if matched is None:
                raise HTTPException(403, 'Workspace is not provisioned')
            return with_plan(settings, dict(matched, roles=[r.value for r in claims.roles], user_id=claims.user_id))
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        for tenant in settings.tenants:
            if hmac.compare_digest(digest, tenant['api_key_sha256']):
                return with_plan(settings, dict(tenant, roles=['TenantAdmin', 'BillingAdmin', 'Viewer']))
        raise HTTPException(401, 'Invalid workspace access key', headers={'WWW-Authenticate': 'Bearer'})
    return current


def require_role(required_role):
    def dependency(user):
        if not user.has_role(required_role):
            raise HTTPException(403, f'{required_role.value} role is required')
        return user
    return dependency


def with_plan(settings, workspace):
    configured = workspace.get('plan_tier', 'STARTER')
    rank = {'STARTER': 0, 'GROWTH': 1, 'ENTERPRISE': 2}

    def effective_tier(persisted):
        if persisted and rank.get(configured, 0) > rank.get(persisted, 0):
            return configured
        return persisted or configured

    # With PostgreSQL enabled, persisted billing state is authoritative unless tenant config grants a higher tier.
    if not settings.database_url:
        return dict(workspace, plan_tier=configured)
    try:
        import psycopg
        with psycopg.connect(settings.database_url, connect_timeout=5) as db:
            db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (workspace['tenant_id'],))
            rows = db.execute('SELECT plan_tier FROM public.organizations WHERE tenant_id=%s', (workspace['tenant_id'],)).fetchall()
            if len(rows) > 1:
                raise ValueError('Ambiguous organization')
        return dict(workspace, plan_tier=effective_tier(rows[0][0] if rows else None))
    except Exception:
        raise HTTPException(503, 'Workspace entitlement state is unavailable') from None


def workspace_response(workspace, mode):
    from app.entitlements import get_tier_entitlements
    from app.cloud_scope import configured_providers
    from app.operations import workspace_operations
    tier = get_tier_entitlements(workspace['plan_tier'])
    return {k: workspace[k] for k in ('tenant_id', 'name', 'subscription_ids', 'roles')} | {
        'mode': mode, 'plan_tier': tier.tier.value, 'max_subscriptions': tier.max_subscriptions,
        'can_export_terraform': tier.can_export_terraform,
        'providers': configured_providers(workspace),
        'max_scopes_per_scan': tier.max_subscriptions,
        'configured_scope_count': sum(len(workspace.get(k, [])) for k in ('subscription_ids','aws_accounts','gcp_projects','kubernetes_clusters')),
        'allowed_scan_frequencies': tier.allowed_scan_frequencies,
        'can_dispatch_automated_alerts': tier.can_dispatch_automated_alerts,
        'retention_days': tier.retention_days,
    } | workspace_operations(workspace['tenant_id'])
