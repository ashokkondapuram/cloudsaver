"""Issue signed offline grants in the same transaction as the immutable issuance audit."""
import os
from pathlib import Path
from datetime import timedelta
from uuid import uuid4
import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from identity.domain import IdentityError,NotFound,scope_ids,configured_providers,uuid_text,text,iso,parse_time


def signer():
    try:
        path=os.environ['PLATFORM_LICENSE_PRIVATE_KEY_FILE']
        kid=os.environ['PLATFORM_LICENSE_KEY_ID']
        issuer=os.environ['PLATFORM_LICENSE_ISSUER']
        audience=os.environ['PLATFORM_LICENSE_AUDIENCE']
        import re
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,64}',kid) or not issuer or not audience:raise ValueError()
        key=load_pem_private_key(Path(path).read_bytes(),password=None)
        if not isinstance(key,RSAPrivateKey) or key.key_size<3072:raise ValueError()
        return key,kid,issuer,audience
    except (OSError,KeyError,ValueError,TypeError,UnsupportedAlgorithm):
        raise IdentityError('Offline licence signing is not configured.',status=503) from None


def issue(service,tenant_id,payload,actor,request_id=None):
    if set(payload)-{'name','roles','all_providers','allowed_providers','scope_restrictions','expires_at'}:
        raise IdentityError('Unsupported licence fields.')
    tenant_id=uuid_text(tenant_id);name=text(payload.get('name'),'Licence name',80)
    key,kid,issuer,audience=signer()
    now=service.now()
    expires=service._expiry(payload.get('expires_at'))
    with service.store.transaction() as tx:
        workspace=tx.get_workspace(tenant_id,lock=True)
        if not workspace:raise NotFound('Workspace not found.')
        customer=tx.get_customer(workspace['customer_id'])
        if workspace['status']!='active' or not customer or customer['status']!='active':
            raise IdentityError('Customer and workspace must be active.')
        service._assert_key_issuance_allowed(tx,workspace)
        grant=service._grant_fields(payload,workspace)
        from identity.billing.projection import workspace_plan_block
        plan=workspace_plan_block(tx,workspace,customer,now)
        if plan.get('access_suspended'):raise IdentityError('Product access is suspended.')
        # A token must not pre-authorize a future unpaid billing period.
        boundary=plan.get('grace_ends_at') if plan.get('billing_state')=='grace' else plan.get('current_period_end')
        if boundary:expires=min(expires,parse_time(boundary,'Billing period end'))
        if expires<=now:raise IdentityError('The current billing entitlement has expired.')
        providers=[p for p in configured_providers(workspace) if (grant['all_providers'] or p in grant['allowed_providers']) and p in plan['entitlements']['allowed_providers']]
        limits=grant.get('scope_restrictions') or {}
        scopes={p:[i for i in scope_ids(workspace,p) if p not in limits or i in limits[p]] for p in providers}
        jti=str(uuid4())
        claims=dict(iss=issuer,aud=audience,iat=int(now.timestamp()),nbf=int(now.timestamp()),exp=int(expires.timestamp()),jti=jti,sub=jti,
                    tenant_id=tenant_id,customer_id=workspace['customer_id'],name=name,roles=grant['roles'],providers=providers,scopes=scopes,plan=plan,schema_version=1)
        if claims['exp']<=claims['iat'] or expires-now>timedelta(days=366):raise IdentityError('Invalid licence duration.')
        token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':kid,'typ':'cloudsaver-license+jwt'})
        if len(token)>12000:raise IdentityError('Licence is too large; issue a narrower scope grant.')
        service._event(tx,actor,'offline_license_issued',tenant_id,None,dict(license_id=jti,name=name,roles=grant['roles'],providers=providers,scopes=scopes,expires_at=iso(expires),signing_key_id=kid),request_id)
    return dict(token=token,license_id=jti,expires_at=iso(expires),roles=grant['roles'],providers=providers,scopes=scopes,plan=plan,validation='offline',revocation='local-denylist-or-expiry')
