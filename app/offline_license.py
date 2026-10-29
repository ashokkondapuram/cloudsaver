"""Offline, pinned-public-key verification of platform-issued bearer licence snapshots."""
from datetime import datetime,timezone
import json
import os
import re
from uuid import UUID

from fastapi import HTTPException
import jwt
from cryptography.exceptions import UnsupportedAlgorithm

MAX_TOKEN_BYTES=12000
MAX_LIFETIME=366*86400


def trust():
    try:
        issuer=os.environ['CLOUDSAVER_LICENSE_ISSUER']
        audience=os.environ['CLOUDSAVER_LICENSE_AUDIENCE']
        keys=json.loads(os.environ['CLOUDSAVER_LICENSE_PUBLIC_KEYS'])
        if not issuer or not audience or not isinstance(keys,dict) or not 1<=len(keys)<=10:raise ValueError()
        result={}
        for kid,pem in keys.items():
            if not re.fullmatch(r'[A-Za-z0-9._-]{1,64}',kid):raise ValueError()
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
            key=load_pem_public_key(pem.encode())
            if not isinstance(key,RSAPublicKey) or key.key_size<3072:raise ValueError()
            result[kid]=key
        return issuer,audience,result
    except (KeyError,ValueError,TypeError,AttributeError,UnsupportedAlgorithm):
        raise ValueError('Configure the offline licence issuer, audience and pinned RSA public keys') from None


class LicenseValidator:
    def workspace(self,token,tenants):
        try:issuer,audience,keys=trust()
        except ValueError:raise HTTPException(503,'Offline licence trust is unavailable') from None
        try:
            if not isinstance(token,str) or len(token)>MAX_TOKEN_BYTES:raise ValueError()
            header=jwt.get_unverified_header(token)
            if set(header)!={'alg','typ','kid'} or header['alg']!='RS256' or header['typ']!='cloudsaver-license+jwt':raise ValueError()
            key=keys.get(header['kid'])
            if key is None:raise ValueError()
            claims=jwt.decode(token,key,algorithms=['RS256'],issuer=issuer,audience=audience,
                              options={'require':['iss','aud','iat','nbf','exp','jti','sub','tenant_id','customer_id','roles','providers','scopes','plan','schema_version']})
            required={'iss','aud','iat','nbf','exp','jti','sub','tenant_id','customer_id','roles','providers','scopes','plan','schema_version','name'}
            if set(claims)!=required or type(claims['schema_version']) is not int or claims['schema_version']!=1:raise ValueError()
            if any(type(claims[t]) is not int for t in ('iat','nbf','exp')):raise ValueError()
            if not claims['iat']<=claims['nbf']<claims['exp'] or not 0<claims['exp']-claims['iat']<=MAX_LIFETIME:raise ValueError()
            for name in ('tenant_id','customer_id','jti','sub'):UUID(claims[name])
            if claims['sub']!=claims['jti'] or not isinstance(claims['name'],str) or not 1<=len(claims['name'])<=80:raise ValueError()
            roles=claims['roles'];providers=claims['providers'];scopes=claims['scopes']
            if not isinstance(roles,list) or not roles or len(set(roles))!=len(roles) or not set(roles)<={'Viewer','BillingAdmin','TenantAdmin'}:raise ValueError()
            if not isinstance(providers,list) or len(set(providers))!=len(providers) or not set(providers)<={'azure','aws','gcp','kubernetes'}:raise ValueError()
            if not isinstance(scopes,dict) or set(scopes)!=set(providers):raise ValueError()
            if any(not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) or not 1<=len(i)<=2048 for i in ids) or len(set(ids))!=len(ids) for ids in scopes.values()):raise ValueError()
            from app.entitlements import normalize_plan
            plan=normalize_plan(claims['plan'])
            if plan is None or plan.get('access_suspended'):raise ValueError()
            if not set(providers)<=set(plan['entitlements']['allowed_providers']):raise ValueError()
            denied=json.loads(os.getenv('CLOUDSAVER_LICENSE_DENIED_IDS','[]'))
            if not isinstance(denied,list) or len(denied)>10000 or any(not isinstance(i,str) for i in denied):raise ValueError()
            if claims['jti'] in denied:raise ValueError()
        except (jwt.PyJWTError,ValueError,TypeError,KeyError,AttributeError):
            raise HTTPException(401,'Invalid, expired or locally revoked licence token',headers={'WWW-Authenticate':'Bearer'}) from None
        matched=next((t for t in tenants if t['tenant_id']==claims['tenant_id'] and t.get('active',True)),None)
        if not matched:raise HTTPException(403,'Workspace is not provisioned or is disabled')
        if matched.get('customer_id') and matched['customer_id']!=claims['customer_id']:
            raise HTTPException(403,'Licence customer does not match this workspace')
        from app.provider_access import narrow,restrict,scope_id,SCOPE_KEYS
        workspace=restrict(narrow(matched,providers),scopes)
        limited={p:ids for p,ids in scopes.items() if set(ids)!=set(scope_id(SCOPE_KEYS[p],item) for item in matched.get(SCOPE_KEYS[p],[]))}
        expires=datetime.fromtimestamp(claims['exp'],timezone.utc).isoformat()
        return dict(workspace,roles=roles,allowed_providers=providers,scope_restrictions=limited or None,
                    plan=plan,plan_tier=plan['code'],identity_provider='offline_license',
                    subject_type='license',subject_id=claims['jti'],key_id=None,key_name=claims['name'],
                    key_expires_at=expires,licence_expires_at=expires,license_id=claims['jti'],customer_roles=[])


def background_workspace(tenant):
    try:
        tokens=json.loads(os.getenv('CLOUDSAVER_BACKGROUND_LICENSES') or '{}')
        token=tokens.get(tenant['tenant_id']) if isinstance(tokens,dict) else None
        if not token:raise HTTPException(403,'No offline licence is installed for background collection')
        return LicenseValidator().workspace(token,[tenant])
    except (ValueError,TypeError):
        raise HTTPException(503,'Background licence configuration is invalid') from None
