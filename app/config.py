"""Fail-closed, operator-managed bootstrap tenant configuration."""
import hashlib
import json
import os
import re
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    mode: str
    database: str
    tenants: tuple
    database_url: str | None = None

    @classmethod
    def load(cls):
        mode = os.getenv('CLOUDSAVER_MODE', 'demo')
        if mode not in ('demo', 'azure'):
            raise ValueError('CLOUDSAVER_MODE must be demo or azure')
        tenants = json.loads(os.getenv('CLOUDSAVER_TENANTS', '[]'))
        if not isinstance(tenants, list):
            raise ValueError('CLOUDSAVER_TENANTS must be a JSON array')
        if not tenants and mode == 'demo':
            key = os.getenv('DEMO_ACCESS_KEY', '')
            if len(key) < 32:
                raise ValueError('Set DEMO_ACCESS_KEY (at least 32 characters) or run scripts/run_demo.py')
            tenants = [dict(tenant_id='11111111-1111-4111-8111-111111111111',
                            name='Northstar Demo',
                            subscription_ids=['22222222-2222-4222-8222-222222222222'],
                            api_key_sha256=hashlib.sha256(key.encode()).hexdigest())]
        if not tenants:
            raise ValueError('Azure mode requires explicit CLOUDSAVER_TENANTS')
        seen_ids, seen_keys = set(), set()
        normalized = []
        for tenant in tenants:
            tid = str(UUID(tenant['tenant_id']))
            name = tenant['name']
            digest = tenant['api_key_sha256']
            subscriptions = [str(UUID(s)) for s in tenant['subscription_ids']]
            if not isinstance(name, str) or not name.strip() or len(name) > 120:
                raise ValueError('Each tenant requires a name of 1–120 characters')
            if not subscriptions or len(subscriptions) > 100 or len(set(subscriptions)) != len(subscriptions):
                raise ValueError('Configure 1–100 unique subscription IDs per tenant')
            if not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('api_key_sha256 must be a lowercase SHA256 hex digest')
            if tid in seen_ids or digest in seen_keys:
                raise ValueError('Tenant IDs and access key hashes must be unique')
            seen_ids.add(tid)
            seen_keys.add(digest)
            normalized.append(dict(tenant_id=tid, name=name.strip(),
                                   subscription_ids=subscriptions, api_key_sha256=digest))
        database = os.getenv('CLOUDSAVER_DB', 'data/cloudsaver.sqlite3')
        return cls(mode, database, tuple(normalized), os.getenv('CLOUDSAVER_DATABASE_URL') or None)
