import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
import jwt
import pytest

from app.auth import EntraIdConfig, EntraTokenValidator, Role, UserClaims

TENANT = '11111111-1111-4111-8111-111111111111'
AUDIENCE = 'cloudsaver-test-api'


@pytest.fixture(scope='module')
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def claims():
    now = int(time.time())
    return dict(tid=TENANT, oid=str(uuid4()), sub='user-subject', aud=AUDIENCE,
                iss=f'https://login.microsoftonline.com/{TENANT}/v2.0', ver='2.0',
                exp=now+300, nbf=now-1, iat=now-1, scp='access_as_user', roles=['Viewer'])


def validator(key):
    return EntraTokenValidator(EntraIdConfig(client_id=AUDIENCE, allowed_tenants={TENANT}),
                               key_resolver=lambda tenant, token: key.public_key())


def token(claims, key):
    return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test-key'})


def test_signed_access_token_and_explicit_roles(signing_key, claims):
    user = validator(signing_key).verify_token(token(claims, signing_key))
    assert user.tenant_id == TENANT and user.has_role(Role.VIEWER)
    assert not user.has_role(Role.TENANT_ADMIN)


@pytest.mark.parametrize('change', [
    {'aud': 'evilcloudsaver-test-api'}, {'aud': [AUDIENCE, 'other-api']}, {'iss': 'https://evil.example/v2.0'},
    {'exp': 1}, {'nbf': 9999999999}, {'iat': 9999999999}, {'ver': '1.0'}, {'oid': 'invalid'},
    {'scp': 'openid profile'}, {'roles': ['GlobalAdmin'], 'wids': ['administrator']},
    {'roles': 'TenantAdmin'}, {'tid': '33333333-3333-4333-8333-333333333333'},
])
def test_rejects_invalid_authorization_claims(signing_key, claims, change):
    claims.update(change)
    with pytest.raises(HTTPException):
        validator(signing_key).verify_token(token(claims, signing_key))


@pytest.mark.parametrize('missing', ['exp', 'nbf', 'iat', 'iss', 'aud', 'tid', 'oid', 'sub', 'ver', 'scp'])
def test_requires_all_access_token_claims(signing_key, claims, missing):
    claims.pop(missing)
    with pytest.raises(HTTPException):
        validator(signing_key).verify_token(token(claims, signing_key))


def test_unsigned_tampered_and_wrong_key_tokens_rejected(signing_key, claims):
    tokens = [jwt.encode(claims, '', algorithm='none'), token(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048))]
    good = token(claims, signing_key)
    parts = good.split('.')
    parts[1] = jwt.encode(dict(claims, roles=['TenantAdmin']), signing_key, algorithm='RS256').split('.')[1]
    tokens.append('.'.join(parts))
    for bad in tokens:
        with pytest.raises(HTTPException) as exc:
            validator(signing_key).verify_token(bad)
        assert exc.value.status_code == 401


def test_unconfigured_identity_fails_closed(signing_key, claims):
    with pytest.raises(HTTPException) as exc:
        EntraTokenValidator(EntraIdConfig()).verify_token(token(claims, signing_key))
    assert exc.value.status_code == 503


def test_cross_tenant_check_after_signature(signing_key, claims):
    with pytest.raises(HTTPException) as exc:
        validator(signing_key).verify_token(token(claims, signing_key), expected_tenant_id=str(uuid4()))
    assert exc.value.status_code == 403


def test_role_hierarchy_is_explicit():
    assert UserClaims(user_id='u', tenant_id=TENANT, roles=[Role.TENANT_ADMIN]).has_role(Role.BILLING_ADMIN)
    assert not UserClaims(user_id='u', tenant_id=TENANT, roles=[Role.BILLING_ADMIN]).has_role(Role.TENANT_ADMIN)
