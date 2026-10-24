"""Service-to-service caller tokens and platform operator authorization for identity-service."""
import hashlib
import hmac
import json
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Header, HTTPException, Request

from identity.config import env

VERIFY_CALLERS = frozenset({'gateway', 'tenant', 'scanner', 'analytics', 'notification', 'agent'})
DIRECTORY_CALLERS = frozenset({'tenant'})
ADMIN_CALLERS = frozenset({'portal'})
OPERATOR, AUDITOR = 'PlatformOperator', 'PlatformAuditor'


def load_callers(raw=None):
    """PLATFORM_IDENTITY_CALLERS holds only SHA-256 digests of caller tokens: {caller: digest}."""
    value = json.loads(env('IDENTITY_CALLERS', '{}') if raw is None else raw)
    if not isinstance(value, dict) or not value:
        raise RuntimeError('Set PLATFORM_IDENTITY_CALLERS (run scripts/setup_platform.py)')
    known = VERIFY_CALLERS | DIRECTORY_CALLERS | ADMIN_CALLERS
    callers = {}
    for name, digest in value.items():
        if name not in known or not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeError('PLATFORM_IDENTITY_CALLERS must map known callers to SHA-256 digests')
        callers[name] = bytes.fromhex(digest)
    return callers


def caller_dependency(callers, allowed):
    def current(x_service_token: str | None = Header(None)):
        if not x_service_token or len(x_service_token) > 256:
            raise HTTPException(401, 'Service authentication required')
        digest = hashlib.sha256(x_service_token.encode()).digest()
        match = None
        for name, expected in callers.items():
            if hmac.compare_digest(digest, expected):
                match = name
        if match is None:
            raise HTTPException(401, 'Service authentication required')
        if match not in allowed:
            raise HTTPException(403, 'This caller is not allowed to use this endpoint')
        return match
    return current


@lru_cache(maxsize=4)
def _jwks(tenant_id):
    return jwt.PyJWKClient(f'https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys',
                           cache_jwk_set=True, lifespan=3600, timeout=5)


class OperatorAuth:
    """Entra workforce tokens (PlatformOperator / PlatformAuditor) or the local operator-key fallback."""

    def __init__(self, mode=None, environment=None, key_resolver=None):
        self.mode = mode or env('PORTAL_AUTH', 'entra')
        self.environment = environment or env('ENVIRONMENT', 'development')
        if self.mode not in ('entra', 'operator_key'):
            raise RuntimeError('PLATFORM_PORTAL_AUTH must be entra or operator_key')
        if self.mode == 'operator_key' and self.environment == 'production':
            raise RuntimeError('The operator-key fallback is not allowed in production')
        self.tenant_id = env('OPERATOR_TENANT_ID', '')
        self.audience = env('IDENTITY_AUDIENCE', 'api://cloudsaver-identity')
        self.key_resolver = key_resolver

    def authenticate(self, token):
        if not token or len(token) > 16384:
            raise HTTPException(401, 'Operator authentication required', headers={'WWW-Authenticate': 'Bearer'})
        if self.mode == 'operator_key':
            expected = (env('OPERATOR_KEY_SHA256') or '').lower()
            if len(expected) != 64:
                raise HTTPException(503, 'Operator sign-in isn\'t configured')
            if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected):
                raise HTTPException(401, 'Invalid operator access key')
            return {'actor': 'operator-key', 'actor_type': 'operator', 'display_name': 'Operator key',
                    'roles': [OPERATOR], 'auth_mode': self.mode}
        return self._entra(token)

    def _entra(self, token):
        if not self.tenant_id:
            raise HTTPException(503, 'Operator sign-in isn\'t configured')
        try:
            tenant = str(UUID(self.tenant_id))
            key = self.key_resolver(token) if self.key_resolver else _jwks(tenant).get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=['RS256'], audience=self.audience,
                                issuer=f'https://login.microsoftonline.com/{tenant}/v2.0',
                                options={'require': ['exp', 'iat', 'iss', 'aud', 'oid', 'tid']})
            if claims['tid'] != tenant:
                raise jwt.InvalidTokenError()
            roles = [r for r in claims.get('roles', []) if r in (OPERATOR, AUDITOR, 'KnowledgeReviewer', 'PrivacyReviewer')]
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503, 'Entra signing keys are temporarily unavailable') from None
        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
            raise HTTPException(401, 'Invalid operator token', headers={'WWW-Authenticate': 'Bearer'}) from None
        if not roles:
            raise HTTPException(403, 'A platform operator or auditor role is required')
        name = str(claims.get('name') or claims.get('preferred_username') or 'Operator')[:70]
        return {'actor': f"{claims['oid']}:{name}"[:120], 'actor_type': 'operator', 'display_name': name,
                'roles': roles, 'auth_mode': self.mode}

    def dependency(self):
        def current(request: Request, authorization: str | None = Header(None)):
            scheme, _, token = (authorization or '').partition(' ')
            if scheme.lower() != 'bearer':
                raise HTTPException(401, 'Operator authentication required', headers={'WWW-Authenticate': 'Bearer'})
            operator = self.authenticate(token.strip())
            roles = set(operator['roles'])
            knowledge_path = request.url.path.startswith('/admin/v1/knowledge/')
            if not roles & {OPERATOR, AUDITOR} and not (knowledge_path or request.url.path == '/admin/v1/session'):
                raise HTTPException(403, 'This role is restricted to knowledge governance')
            review = (request.method == 'POST' and knowledge_path and request.url.path.endswith('/review')
                      and bool(roles & {'KnowledgeReviewer', 'PrivacyReviewer'}))
            if request.method != 'GET' and OPERATOR not in roles and not review:
                raise HTTPException(403, 'The PlatformOperator role is required')
            return operator
        return current
