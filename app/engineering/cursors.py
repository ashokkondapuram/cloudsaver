"""Short-lived HMAC cursors bound to principal, authorization, operation and page size."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from uuid import UUID
from app.control_plane.plans import digest
from app.principals import actor

_LOCAL_KEY = secrets.token_bytes(32)


def context(tenant, operation, limit):
    return digest(dict(tenant_id=tenant['tenant_id'], actor=actor(tenant), operation=operation, limit=limit,
                       allowed_providers=sorted(tenant.get('allowed_providers') or []) if tenant.get('allowed_providers') is not None else None,
                       scopes=tenant.get('scope_restrictions'), subscriptions=sorted(tenant.get('subscription_ids',[])), schema=1))


class Cursors:
    def __init__(self):
        value = os.getenv('CLOUDSAVER_ENGINEERING_CURSOR_KEY','')
        if value and len(value.encode()) < 32:
            raise ValueError('Engineering cursor signing key must be at least 32 bytes')
        if os.getenv('CLOUDSAVER_ENVIRONMENT') in ('production','staging') and not value:
            raise ValueError('Set CLOUDSAVER_ENGINEERING_CURSOR_KEY consistently on core replicas')
        self.key = value.encode() if value else _LOCAL_KEY

    def encode(self, last_id, binding):
        raw = json.dumps({'id':str(UUID(last_id)), 'binding':binding, 'expires':int(time.time())+900},sort_keys=True,separators=(',',':')).encode()
        body = base64.urlsafe_b64encode(raw).rstrip(b'=')
        return (body+b'.'+hmac.new(self.key,body,hashlib.sha256).hexdigest().encode()).decode()

    def decode(self, value, binding):
        try:
            if not isinstance(value,str) or len(value)>1000:raise ValueError()
            body, signature = value.encode().split(b'.')
            if not hmac.compare_digest(signature,hmac.new(self.key,body,hashlib.sha256).hexdigest().encode()):raise ValueError()
            data=json.loads(base64.b64decode(body+b'='*(-len(body)%4),altchars=b'-_',validate=True))
            if set(data)!={'id','binding','expires'} or data['binding']!=binding or type(data['expires']) is not int or data['expires']<=time.time():raise ValueError()
            return str(UUID(data['id']))
        except (ValueError,TypeError,KeyError,UnicodeError):
            raise ValueError('Cursor is invalid, expired or belongs to a different authorization/query context') from None
