"""Tenant-bound operator integrations; never accept destinations from API callers."""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class Target:
    target_id: str
    tenant_id: str
    channel: str
    url: str = field(repr=False)

    @property
    def fingerprint(self):
        return hashlib.sha256(f'{self.tenant_id}|{self.channel}|{self.url}'.encode()).hexdigest()

    def public(self):
        return {'target_id': self.target_id, 'channel': self.channel}


def target_definitions():
    """Validate public bindings without resolving secrets in identity/gateway services."""
    try:
        raw=os.getenv('CLOUDSAVER_NOTIFICATION_TARGETS','[]')
        if len(raw)>32000:
            raise ValueError()
        rows=json.loads(raw)
        if not isinstance(rows,list) or len(rows)>100:
            raise ValueError()
        result,seen=[],set()
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'target_id','tenant_id','channel','url_env'}:
                raise ValueError()
            tid=str(UUID(row['tenant_id']))
            name,variable=row['target_id'],row['url_env']
            if not isinstance(name,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,39}',name):
                raise ValueError()
            if not isinstance(variable,str) or not re.fullmatch('CLOUDSAVER_WEBHOOK_[A-Z0-9_]{1,64}',variable):
                raise ValueError()
            if row['channel'] not in ('slack','teams') or (tid,name) in seen:
                raise ValueError()
            seen.add((tid,name))
            result.append(dict(row,tenant_id=tid))
        return tuple(result)
    except (ValueError,KeyError,TypeError,AttributeError):
        raise ValueError('Notification target configuration is invalid') from None


def load_targets():
    from services.notification import webhook_url
    from urllib.parse import urlsplit
    try:
        result=[]
        for row in target_definitions():
            url=os.getenv(row['url_env'],'')
            if len(url)>4096:
                raise ValueError()
            webhook_url(url)
            if (urlsplit(url).hostname=='hooks.slack.com') != (row['channel']=='slack'):
                raise ValueError()
            result.append(Target(row['target_id'],row['tenant_id'],row['channel'],url))
        return tuple(result)
    except (ValueError,KeyError,TypeError,AttributeError):
        raise ValueError('Notification target configuration is invalid') from None


def enabled():
    return os.getenv('CLOUDSAVER_DELIVERY_ENABLED','false').lower() == 'true'
