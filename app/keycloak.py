"""Keycloak authentication with current server-side roles and tenant licence checks.

Trusted operator bindings select every endpoint. JWTs never select a URL or
grant a licence. The realm's protected tenant group carries the licence record;
only its administrators may edit that attribute.
"""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID
from typing import Annotated

import httpx
import jwt
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Binding(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    tenant_id:str
    issuer:str
    audience:str=Field(min_length=1,max_length=100)
    client_id:str=Field(min_length=1,max_length=100)
    client_uuid:str
    secret_env:str=Field(pattern=r'^CLOUDSAVER_KEYCLOAK_SECRET_[A-Z0-9_]{1,80}$')
    group_id:str
    authorized_parties:list[Annotated[str,Field(min_length=1,max_length=100)]]=Field(min_length=1,max_length=20)

    @field_validator('tenant_id','client_uuid','group_id')
    @classmethod
    def uuid(cls,value):return str(UUID(value))

    @field_validator('issuer')
    @classmethod
    def endpoint(cls,value):
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or not re.fullmatch(r'(?:/[A-Za-z0-9._~-]+)*/realms/[A-Za-z0-9._~-]+',p.path):
            raise ValueError('Keycloak issuer must be an exact trusted HTTPS realm URL')
        return value

    @property
    def admin_url(self):
        base,realm=self.issuer.rsplit('/realms/',1)
        return base+'/admin/realms/'+realm


def bindings():
    try:
        rows=json.loads(os.getenv('CLOUDSAVER_KEYCLOAK_BINDINGS','[]'))
        if not isinstance(rows,list) or not 1<=len(rows)<=100:raise ValueError()
        parsed=[Binding.model_validate(r) for r in rows]
        if len({b.tenant_id for b in parsed})!=len(parsed):raise ValueError()
        # Client roles must never grant an administrator rights in another tenant.
        if len({(b.issuer,b.client_uuid) for b in parsed})!=len(parsed):raise ValueError()
        return {b.tenant_id:b for b in parsed}
    except (ValueError,TypeError):
        raise ValueError('Configure valid unique CLOUDSAVER_KEYCLOAK_BINDINGS') from None


@lru_cache(maxsize=100)
def signing_keys(issuer):
    return jwt.PyJWKClient(issuer+'/protocol/openid-connect/certs',cache_jwk_set=True,lifespan=300,timeout=5)


class KeycloakValidator:
    def __init__(self,configuration=None,*,key_resolver=None,transport=None):
        self.bindings=configuration if configuration is not None else bindings()
        self.key_resolver=key_resolver
        self.transport=transport
        self._tokens={}
        self._lock=threading.Lock()

    def _request(self,client,method,url,**kwargs):
        try:
            remaining=getattr(client,'cloudsaver_deadline',time.monotonic()+5)-time.monotonic()
            if remaining<=0:raise ValueError()
            with client.stream(method,url,timeout=httpx.Timeout(min(5,remaining),connect=min(2,remaining)),**kwargs) as response:
                if response.status_code!=200:
                    raise HTTPException(503,'Identity verification is temporarily unavailable')
                data=bytearray()
                for part in response.iter_bytes():
                    data.extend(part)
                    if len(data)>1_000_000 or time.monotonic()>getattr(client,'cloudsaver_deadline',float('inf')):raise ValueError()
                return json.loads(data)
        except HTTPException:raise
        except (httpx.HTTPError,ValueError,TypeError):
            raise HTTPException(503,'Identity verification is temporarily unavailable') from None

    def _admin_token(self,client,binding,secret):
        key=(binding.issuer,binding.client_id,hashlib.sha256(secret.encode()).hexdigest())
        with self._lock:
            cached=self._tokens.get(key)
            if cached and cached[0]>time.monotonic():return cached[1]
            result=self._request(client,'POST',binding.issuer+'/protocol/openid-connect/token',
                data=dict(grant_type='client_credentials',client_id=binding.client_id,client_secret=secret))
            token=result.get('access_token') if isinstance(result,dict) else None
            expires=result.get('expires_in') if isinstance(result,dict) else None
            if not isinstance(token,str) or not token or len(token)>16384 or type(expires) is not int or expires<=5:
                raise HTTPException(503,'Identity service credential is unavailable')
            self._tokens={k:v for k,v in self._tokens.items() if v[0]>time.monotonic()}
            if len(self._tokens)>=100:self._tokens.clear()
            self._tokens[key]=(time.monotonic()+min(30,expires-5),token)
            return token

    def workspace(self,token,tenants):
        try:
            if not isinstance(token,str) or len(token)>16384:raise ValueError()
            unverified=jwt.decode(token,options={'verify_signature':False})
            tid=str(UUID(unverified['cloudsaver_tenant_id']))
            binding=self.bindings.get(tid)
            matched=next((t for t in tenants if t['tenant_id']==tid and t.get('active',True)),None)
            if not binding or matched is None:raise ValueError()
            header=jwt.get_unverified_header(token)
            if header.get('alg')!='RS256' or not isinstance(header.get('kid'),str) or not header['kid']:raise ValueError()
            key=self.key_resolver(binding,token) if self.key_resolver else signing_keys(binding.issuer).get_signing_key_from_jwt(token).key
            claims=jwt.decode(token,key,algorithms=['RS256'],audience=binding.audience,issuer=binding.issuer,
                              options={'require':['exp','iat','iss','aud','sub','azp','cloudsaver_tenant_id']})
            uid=str(UUID(claims['sub']))
            if claims.get('typ')!='Bearer' or claims['azp'] not in binding.authorized_parties or claims['cloudsaver_tenant_id']!=tid:
                raise ValueError()
            if type(claims['iat']) is not int or type(claims['exp']) is not int or not 0<claims['exp']-claims['iat']<=300:
                raise ValueError()
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503,'Identity signing keys are temporarily unavailable') from None
        except (jwt.PyJWTError,ValueError,TypeError,KeyError,AttributeError):
            raise HTTPException(401,'Invalid Keycloak access token',headers={'WWW-Authenticate':'Bearer'}) from None
        secret=os.getenv(binding.secret_env,'')
        if not secret:raise HTTPException(503,'Identity service credential is unavailable')
        with httpx.Client(timeout=httpx.Timeout(5,connect=2),follow_redirects=False,transport=self.transport) as client:
            client.cloudsaver_deadline=time.monotonic()+15
            active=self._request(client,'POST',binding.issuer+'/protocol/openid-connect/token/introspect',
                data=dict(token=token,client_id=binding.client_id,client_secret=secret))
            if not isinstance(active,dict) or active.get('active') is not True or active.get('sub')!=uid:
                raise HTTPException(401,'Keycloak session expired or was revoked')
            headers={'Authorization':'Bearer '+self._admin_token(client,binding,secret)}
            user=self._request(client,'GET',binding.admin_url+'/users/'+uid,headers=headers)
            if not isinstance(user,dict) or user.get('id')!=uid or user.get('enabled') is not True:
                raise HTTPException(403,'Client access is disabled')
            member=False
            for first in range(0,2000,100):
                groups=self._request(client,'GET',binding.admin_url+'/users/'+uid+'/groups',headers=headers,params={'first':first,'max':100,'briefRepresentation':'true'})
                if not isinstance(groups,list) or len(groups)>100 or any(not isinstance(g,dict) for g in groups):
                    raise HTTPException(503,'Identity membership is unavailable')
                if any(g.get('id')==binding.group_id for g in groups):member=True;break
                if len(groups)<100:break
            if not member:raise HTTPException(403,'Client membership is required')
            roles=self._request(client,'GET',binding.admin_url+f'/users/{uid}/role-mappings/clients/{binding.client_uuid}/composite',headers=headers)
            if not isinstance(roles,list) or len(roles)>1000 or any(not isinstance(r,dict) for r in roles):
                raise HTTPException(503,'Identity roles are unavailable')
            from app.auth import Role
            allowed=[r['name'] for r in roles if isinstance(r.get('name'),str) and r['name'] in Role._value2member_map_]
            if not allowed:raise HTTPException(403,'An assigned CloudSaver client role is required')
            plan,expires=self._licence(client,binding,headers)
        service=bool(user.get('serviceAccountClientId'))
        return dict(matched,roles=allowed,subject_type='service_account' if service else 'user',subject_id=uid,
                    **({} if service else {'user_id':uid}),key_id=None,allowed_providers=None,plan=plan,
                    plan_tier=plan['code'],identity_provider='keycloak',licence_expires_at=expires.isoformat())

    def _licence(self,client,binding,headers):
        group=self._request(client,'GET',binding.admin_url+'/groups/'+binding.group_id,headers=headers)
        try:
            if group.get('id')!=binding.group_id:raise ValueError()
            values=group['attributes']['cloudsaver_license']
            if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],str) or len(values[0])>10000:raise ValueError()
            licence=json.loads(values[0])
            if (not isinstance(licence,dict) or set(licence)!={'schema_version','enabled','expires_at','plan'}
                or type(licence['schema_version']) is not int or licence['schema_version']!=1 or type(licence['enabled']) is not bool):raise ValueError()
            expires=datetime.fromisoformat(licence['expires_at'].replace('Z','+00:00'))
            if not expires.tzinfo:raise ValueError()
            from app.entitlements import normalize_plan
            plan=normalize_plan(licence['plan'])
            if plan is None:raise ValueError()
        except (ValueError,KeyError,TypeError,AttributeError):
            raise HTTPException(503,'The client licence record is invalid or unavailable') from None
        if not licence['enabled'] or expires<=datetime.now(timezone.utc) or plan.get('access_suspended'):
            raise HTTPException(403,'The client licence is disabled or expired')
        return plan,expires

    def licensed_workspace(self,tenant):
        """Current tenant licence for explicitly configured background collection grants."""
        binding=self.bindings.get(tenant['tenant_id'])
        if not binding or not tenant.get('active',True):raise HTTPException(403,'Client access is disabled')
        secret=os.getenv(binding.secret_env,'')
        if not secret:raise HTTPException(503,'Identity service credential is unavailable')
        with httpx.Client(follow_redirects=False,transport=self.transport) as client:
            client.cloudsaver_deadline=time.monotonic()+10
            headers={'Authorization':'Bearer '+self._admin_token(client,binding,secret)}
            plan,expires=self._licence(client,binding,headers)
        return dict(tenant,plan=plan,plan_tier=plan['code'],identity_provider='keycloak',licence_expires_at=expires.isoformat())


@lru_cache(maxsize=1)
def background_validator():
    return KeycloakValidator()


def current_licence(tenant):
    if os.getenv('CLOUDSAVER_AUTH_MODE')!='keycloak':return tenant
    return background_validator().licensed_workspace(tenant)
