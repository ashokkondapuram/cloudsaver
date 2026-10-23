"""Customer bootstrap claim and customer access administration, proxied to identity-service.

Identity re-verifies the caller's key on every /customer/v1 call and enforces customer roles; this
module only fixes the upstream paths and pins workspace-level calls to the caller's own workspace.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

UNAVAILABLE = 'Sign-in is temporarily unavailable. Try again in a few minutes.'
EMAIL_ISSUER = 'urn:cloudsaver:email'
KEY_ID = r'^[A-Za-z0-9]{12}$'


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(None, max_length=320, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    idp_issuer: str | None = Field(None, max_length=512)
    idp_subject: str | None = Field(None, max_length=256)

    @model_validator(mode='after')
    def identity(self):
        if bool(self.idp_issuer) != bool(self.idp_subject):
            raise ValueError('Include both the identity issuer and subject.')
        if not self.idp_issuer and not self.email:
            raise ValueError('Enter your work email.')
        return self

    def upstream(self):
        issuer, subject = self.idp_issuer, self.idp_subject
        if not issuer:
            issuer, subject = EMAIL_ISSUER, self.email.strip().lower()
        return {'key': self.key, 'idp_issuer': issuer, 'idp_subject': subject,
                'display_name': self.display_name.strip(), 'email': self.email}


def _call(method, path, *, authorization=None, json=None, params=None, raw=False):
    from app.identity_client import IdentityUnavailable, shared_client
    from app.runtime import client_ip
    headers = {}
    if authorization:
        headers['Authorization'] = authorization
    if client_ip.get():
        headers['X-Forwarded-For'] = client_ip.get()
    try:
        response = shared_client().request(method, path, json=json, params=params, headers=headers)
    except (IdentityUnavailable, RuntimeError):
        raise HTTPException(503, UNAVAILABLE) from None
    if response.status_code >= 400:
        detail = 'We could not complete this request. Try again or contact Support.'
        try:
            candidate = response.json().get('detail')
            if isinstance(candidate, str) and 0 < len(candidate) <= 300:
                detail = candidate
        except (ValueError, AttributeError):
            pass
        status = response.status_code if response.status_code in (401, 403, 404, 409, 422, 429) else 502
        raise HTTPException(status, detail)
    if raw:
        return response
    return response.json()


def onboarding_router():
    # Full paths, not include prefixes: route classification reads the route's own path.
    router = APIRouter(tags=['onboarding'])

    @router.post('/api/v1/onboarding/claim')
    def claim(payload: ClaimRequest):
        try:
            return _call('POST', '/customer/v1/claim', json=payload.upstream())
        except HTTPException as exc:
            if exc.status_code == 401:
                raise HTTPException(401, 'This onboarding key is invalid or has expired. '
                                         'Ask your administrator for a new key.') from None
            raise

    return router


class Invite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=320, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    role: str = Field('CustomerAdmin', pattern='^(CustomerAdmin|CustomerAuditor)$')


class Reason(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str | None = Field(None, max_length=200)


class Transfer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: UUID


class Member(BaseModel):
    model_config = ConfigDict(extra='forbid')
    roles: list[str] = Field(min_length=1, max_length=3)
    version: int = Field(ge=0)


class Versioned(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=0)


class ServiceAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(None, max_length=500)


class ServiceAccountChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=0)
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=500)
    status: str | None = Field(None, pattern='^(active|suspended|deleted)$')


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    roles: list[str] = Field(min_length=1, max_length=3)
    all_providers: bool = True
    allowed_providers: list[str] = Field(default_factory=list, max_length=4)
    scope_restrictions: dict[str, list[str]] | None = None
    expires_at: str = Field(max_length=40)
    subject_user_id: UUID | None = None
    service_account_id: UUID | None = None


class Rotate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    overlap_hours: int = Field(24, ge=0, le=168)
    expires_at: str | None = Field(None, max_length=40)


def customer_access_router(workspace_dependency):
    """Routes for the dashboard Access tab. Workspace-level calls always use the caller's workspace."""
    router = APIRouter(prefix='/api/v1/customer', tags=['customer-access'])
    user_id = Path(pattern=r'^[0-9a-fA-F-]{36}$')

    def body(model):
        return model.model_dump(mode='json', exclude_none=True)

    @router.get('/me')
    def me(row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('GET', '/customer/v1/me', authorization=authorization)

    @router.get('/users')
    def users(row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('GET', '/customer/v1/users', authorization=authorization)

    @router.post('/users/invite', status_code=201)
    def invite(payload: Invite, row=Depends(workspace_dependency), authorization: str = Header()):
        upstream = body(payload) | {'idp_issuer': EMAIL_ISSUER, 'idp_subject': payload.email.strip().lower()}
        return _call('POST', '/customer/v1/users/invite', authorization=authorization, json=upstream)

    @router.post('/users/{user_id}/suspend')
    def suspend(payload: Reason, user_id: str = user_id, row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('POST', f'/customer/v1/users/{user_id}/suspend', authorization=authorization, json=body(payload))

    @router.post('/users/{user_id}/reactivate')
    def reactivate(payload: Reason, user_id: str = user_id, row=Depends(workspace_dependency),
                   authorization: str = Header()):
        return _call('POST', f'/customer/v1/users/{user_id}/reactivate', authorization=authorization, json=body(payload))

    @router.post('/ownership/transfer')
    def transfer(payload: Transfer, row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('POST', '/customer/v1/ownership/transfer', authorization=authorization, json=body(payload))

    @router.get('/members')
    def members(row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('GET', f'/customer/v1/workspaces/{row["tenant_id"]}/members', authorization=authorization)

    @router.put('/members/{user_id}')
    def set_member(payload: Member, user_id: str = user_id, row=Depends(workspace_dependency),
                   authorization: str = Header()):
        return _call('PUT', f'/customer/v1/workspaces/{row["tenant_id"]}/members/{user_id}',
                     authorization=authorization, json=body(payload))

    @router.post('/members/{user_id}/remove')
    def remove_member(payload: Versioned, user_id: str = user_id, row=Depends(workspace_dependency),
                      authorization: str = Header()):
        return _call('POST', f'/customer/v1/workspaces/{row["tenant_id"]}/members/{user_id}/remove',
                     authorization=authorization, json=body(payload))

    @router.get('/service-accounts')
    def service_accounts(row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('GET', '/customer/v1/service-accounts', authorization=authorization)

    @router.post('/service-accounts', status_code=201)
    def create_service_account(payload: ServiceAccount, row=Depends(workspace_dependency),
                               authorization: str = Header()):
        return _call('POST', '/customer/v1/service-accounts', authorization=authorization, json=body(payload))

    @router.patch('/service-accounts/{account_id}')
    def update_service_account(payload: ServiceAccountChange, account_id: str = user_id,
                               row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('PATCH', f'/customer/v1/service-accounts/{account_id}', authorization=authorization,
                     json=body(payload))

    @router.get('/keys')
    def keys(row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('GET', f'/customer/v1/workspaces/{row["tenant_id"]}/keys', authorization=authorization)

    @router.post('/keys', status_code=201)
    def issue_key(payload: KeyRequest, row=Depends(workspace_dependency), authorization: str = Header()):
        return _call('POST', f'/customer/v1/workspaces/{row["tenant_id"]}/keys', authorization=authorization,
                     json=body(payload))

    @router.post('/keys/{key_id}/revoke')
    def revoke_key(payload: Reason, key_id: str = Path(pattern=KEY_ID), row=Depends(workspace_dependency),
                   authorization: str = Header()):
        return _call('POST', f'/customer/v1/keys/{key_id}/revoke', authorization=authorization, json=body(payload))

    @router.post('/keys/{key_id}/rotate', status_code=201)
    def rotate_key(payload: Rotate, key_id: str = Path(pattern=KEY_ID), row=Depends(workspace_dependency),
                   authorization: str = Header()):
        return _call('POST', f'/customer/v1/keys/{key_id}/rotate', authorization=authorization, json=body(payload))

    @router.get('/audit')
    def audit(row=Depends(workspace_dependency), authorization: str = Header(),
              limit: int = Query(50, ge=1, le=200), before: str | None = Query(None, max_length=40)):
        params = {'limit': limit} | ({'before': before} if before else {})
        return _call('GET', '/customer/v1/audit', authorization=authorization, params=params)

    @router.get('/access-export')
    def access_export(row=Depends(workspace_dependency), authorization: str = Header()):
        response = _call('GET', '/customer/v1/access-export', authorization=authorization, raw=True)
        return Response(response.content, media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="access-review.csv"'})

    return router
