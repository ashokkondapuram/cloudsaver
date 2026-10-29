"""Verify the selected identity mode before deriving scoped workspace access."""
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


ALL_ROLES = ['TenantAdmin', 'BillingAdmin', 'Viewer']
INVALID_KEY = 'Invalid workspace access key'
REJECTIONS = {
    'revoked': (401, 'This workspace key has expired or was revoked. Ask your CloudSaver administrator for a new key.'),
    'expired': (401, 'This workspace key has expired or was revoked. Ask your CloudSaver administrator for a new key.'),
    'rotated_out': (401, 'This workspace key has expired or was revoked. Ask your CloudSaver administrator for a new key.'),
    'workspace_suspended': (403, 'This workspace is suspended. Contact your CloudSaver administrator.'),
    'suspended': (403, 'This workspace is suspended. Contact your CloudSaver administrator.'),
}
SIGN_IN_UNAVAILABLE = 'Sign-in is temporarily unavailable. Try again in a few minutes.'
SETTING_UP = 'This workspace is still being set up. Try again in a few seconds.'
_shadow_pool = None


def _tenants(settings):
    try:
        return settings.tenants
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Workspace directory is unavailable') from None


def local_workspace(settings, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    match = None
    for tenant in _tenants(settings):
        if tenant.get('api_key_sha256') and hmac.compare_digest(digest, tenant['api_key_sha256']):
            match = tenant
    if match is None:
        raise HTTPException(401, INVALID_KEY, headers={'WWW-Authenticate': 'Bearer'})
    return dict(match, roles=list(ALL_ROLES), allowed_providers=None)


def identity_workspace(settings, client, token, client_ip, request_id):
    from app.identity_client import IdentityUnavailable, KeyRejected
    from app.entitlements import normalize_plan
    from app.provider_access import narrow, restrict
    try:
        grant = client.verify(token, client_ip, request_id)
    except KeyRejected as exc:
        if exc.reason == 'throttled':
            raise HTTPException(429, 'Too many sign-in attempts. Try again in 15 minutes.',
                                headers={'Retry-After': str(exc.retry_after or 900)}) from None
        status, detail = REJECTIONS.get(exc.reason, (401, INVALID_KEY))
        raise HTTPException(status, detail, headers={'WWW-Authenticate': 'Bearer'} if status == 401 else None) from None
    except IdentityUnavailable:
        raise HTTPException(503, SIGN_IN_UNAVAILABLE) from None
    matched = next((t for t in _tenants(settings) if t['tenant_id'] == grant['tenant_id']), None)
    projected = matched.get('directory_version') if matched else None
    if matched is None or (projected is not None and projected < grant['directory_version']):
        raise HTTPException(503, SETTING_UP, headers={'Retry-After': '5'})
    allowed = None if grant['all_providers'] else list(grant['allowed_providers'])
    workspace = narrow(matched, allowed) if allowed is not None else dict(matched)
    limits = grant.get('scope_restrictions') or None
    if limits:
        workspace = restrict(workspace, limits)
    try:
        plan = normalize_plan(grant.get('plan'))
    except ValueError:
        import logging
        logging.getLogger('cloudsaver.identity').warning('Ignoring a malformed verify plan block')
        plan = None
    if plan is not None:
        # The verify response is fresher than the projection, so its plan wins.
        workspace = dict(workspace, plan=plan, plan_tier=plan['code'])
    expiries = [v for v in (grant.get('expires_at'), grant.get('rotates_out_at')) if v]
    return dict(workspace, roles=list(grant['roles']), key_id=grant['key_id'], key_name=grant['key_name'],
                allowed_providers=allowed, key_expires_at=min(expiries) if expiries else None,
                scope_restrictions=limits, customer_roles=list(grant.get('customer_roles') or []),
                subject_type=grant.get('subject_type') or 'operator', subject_id=grant.get('subject_id'))


def _shadow(client, token, client_ip, request_id, local_tenant):
    """Shadow mode: compare identity-service with the local result without affecting the response."""
    import logging
    from app.identity_client import KeyRejected
    log = logging.getLogger('cloudsaver.identity.shadow')
    try:
        remote = client.verify(token, client_ip, request_id)['tenant_id']
    except KeyRejected:
        remote = None
    except Exception:
        log.warning('Shadow verification unavailable')
        return
    if remote != local_tenant:
        log.warning('Shadow verification mismatch local=%s identity=%s', 'valid' if local_tenant else 'invalid',
                    'valid' if remote else 'invalid')


def tenant_dependency(settings, validator=None, identity_client=None):
    from fastapi import Request
    from starlette.concurrency import run_in_threadpool
    from app.config import key_verifier
    from app.cloud_scope import configured_providers
    from app.provider_access import access, enforce_route
    from app.runtime import client_ip, request_id
    mode = os.getenv('CLOUDSAVER_AUTH_MODE', 'workspace')
    if mode not in ('workspace', 'entra', 'keycloak', 'license'):
        raise ValueError('CLOUDSAVER_AUTH_MODE must be workspace, entra, keycloak or license')
    verifier = key_verifier() if mode == 'workspace' else 'local'
    own_validator = validator is None
    if mode=='license':
        from app.config import directory_mode
        if directory_mode()!='registry':raise ValueError('Offline licence mode requires CLOUDSAVER_DIRECTORY_MODE=registry')
        from app.offline_license import LicenseValidator
        validator=validator or LicenseValidator()
    elif mode=='keycloak':
        from app.keycloak import KeycloakValidator
        validator=validator or KeycloakValidator()
    else:
        validator = validator or EntraTokenValidator(EntraIdConfig(allowed_tenants={t['tenant_id'] for t in settings.tenants}))
    bearer = HTTPBearer(auto_error=False)

    def client():
        if identity_client is not None:
            return identity_client
        from app.identity_client import shared_client
        return shared_client()

    def entra(token):
        tenants = _tenants(settings)
        if own_validator:
            validator.config.allowed_tenants = {t['tenant_id'] for t in tenants}
        claims = validator.verify_token(token)
        matched = next((t for t in tenants if t['tenant_id'] == claims.tenant_id), None)
        if matched is None:
            raise HTTPException(403, 'Workspace is not provisioned')
        return with_plan(settings, dict(matched, roles=[r.value for r in claims.roles], user_id=claims.user_id,
                                        subject_type='user',subject_id=claims.user_id,allowed_providers=None))

    def workspace(token, ip, rid):
        if verifier == 'identity':
            result = identity_workspace(settings, client(), token, ip, rid)
        else:
            try:
                result = local_workspace(settings, token)
            except HTTPException:
                if verifier == 'shadow':
                    shadow(token, ip, rid, None)
                raise
            if verifier == 'shadow':
                shadow(token, ip, rid, result['tenant_id'])
        return with_plan(settings, result)

    def shadow(token, ip, rid, local_tenant):
        try:
            _submit_shadow(client(), token, ip, rid, local_tenant)
        except Exception:
            import logging
            logging.getLogger('cloudsaver.identity.shadow').warning('Shadow verification is not configured')

    async def current(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        access.set(None)
        if not credentials or credentials.scheme.lower() != 'bearer':
            raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
        from app.config import require_directory_freshness
        try:await run_in_threadpool(require_directory_freshness,settings)
        except Exception:raise HTTPException(503,'Workspace directory is not fresh enough to authorize access',headers={'Retry-After':'5'}) from None
        token = credentials.credentials
        if mode in ('keycloak','license'):
            result=await run_in_threadpool(validator.workspace,token,_tenants(settings))
        else:
            result = (await run_in_threadpool(entra, token) if mode=='entra' else
                      await run_in_threadpool(workspace, token, client_ip.get(), request_id.get()))
        if (result.get('plan') or {}).get('access_suspended') is True:
            if not (request.url.path.startswith('/api/v1/customer/') or request.url.path.startswith('/api/v1/billing/')
                    or request.url.path == '/api/v1/me'):
                raise HTTPException(403, 'Product access is suspended by billing policy. Security and billing administration remain available.')
        if result.get('allowed_providers') is not None or result.get('scope_restrictions'):
            source = next((t for t in _tenants(settings) if t['tenant_id'] == result['tenant_id']), result)
            route = request.scope.get('route')
            enforce_route(request.method, getattr(route, 'path', request.url.path), result, configured_providers(source))
        return result
    return current


def _submit_shadow(client, token, ip, rid, local_tenant):
    global _shadow_pool
    from concurrent.futures import ThreadPoolExecutor
    if _shadow_pool is None:
        _shadow_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='identity-shadow')
    _shadow_pool.submit(_shadow, client, token, ip, rid, local_tenant)


def require_role(required_role):
    def dependency(user):
        if not user.has_role(required_role):
            raise HTTPException(403, f'{required_role.value} role is required')
        return user
    return dependency


def with_plan(settings, workspace):
    """Attach the effective plan: verified plan block, else projected entitlements, else the TIER_LIMITS fallback."""
    from app.entitlements import entitlements_for
    plan = entitlements_for(workspace)
    return dict(workspace, plan_tier=plan.tier, plan_name=plan.plan_name, billing_state=plan.billing_state)


def workspace_response(workspace, mode, settings=None):
    from app.entitlements import entitlements_for
    from app.cloud_scope import configured_providers
    from app.operations import workspace_operations
    from app.config import directory_mode
    tier = entitlements_for(workspace)
    providers = configured_providers(workspace)
    cutover = directory_mode() == 'cutover'
    return {k: workspace[k] for k in ('tenant_id', 'name', 'subscription_ids', 'roles')} | {
        'allowed_providers': providers, 'key_id': workspace.get('key_id'), 'key_name': workspace.get('key_name'),
        'key_expires_at': workspace.get('key_expires_at'), 'all_providers': workspace.get('allowed_providers') is None,
        'scope_restrictions': workspace.get('scope_restrictions'), 'customer_roles': workspace.get('customer_roles', []),
        'subject_type': workspace.get('subject_type', 'operator'), 'subject_id': workspace.get('subject_id'),
        'directory_mode': directory_mode(), 'scopes_editable': not cutover,
        'identity_provider':workspace.get('identity_provider','entra' if os.getenv('CLOUDSAVER_AUTH_MODE')=='entra' else 'platform'),
        'licence_expires_at':workspace.get('licence_expires_at'),
        'mode': mode, 'plan_tier': tier.tier, 'plan_name': tier.plan_name, 'billing_state': tier.billing_state,
        'max_subscriptions': tier.max_subscriptions,
        'can_export_terraform': tier.can_export_terraform,
        'can_use_ai_advisory': tier.can_use_ai_advisory,
        'providers': providers,
        'max_scopes_per_scan': tier.max_subscriptions,
        'configured_scope_count': sum(len(workspace.get(k, [])) for k in ('subscription_ids','aws_accounts','gcp_projects','kubernetes_clusters')),
        'allowed_scan_frequencies': tier.allowed_scan_frequencies,
        'can_dispatch_automated_alerts': tier.can_dispatch_automated_alerts,
        'retention_days': tier.retention_days,
        'settings_editable': getattr(settings, 'registry', None) is not None,
    } | workspace_operations(workspace, settings)
