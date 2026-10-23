"""Fail-closed bootstrap configuration with an optional database tenant registry."""
import hashlib
import json
import os
from dataclasses import dataclass, field


def bootstrap_tenants(raw=None, *, required=True):
    from app.tenant_config import normalize_tenant
    tenants = json.loads(os.getenv('CLOUDSAVER_TENANTS', '[]') if raw is None else raw)
    if not isinstance(tenants, list):
        raise ValueError('CLOUDSAVER_TENANTS must be a JSON array')
    if not tenants and required:
        raise ValueError('Configure explicit CLOUDSAVER_TENANTS (run scripts/setup_compose.py for a local workspace)')
    seen_ids, seen_keys, normalized = set(), set(), []
    for tenant in tenants:
        if isinstance(tenant, dict) and not tenant.get('api_key_sha256') and os.getenv('CLOUDSAVER_AUTH_MODE') == 'entra':
            tenant = dict(tenant, api_key_sha256=hashlib.sha256(os.urandom(32)).hexdigest())
        row = normalize_tenant(tenant, require_scope=True)
        if row['tenant_id'] in seen_ids or row['api_key_sha256'] in seen_keys:
            raise ValueError('Workspace IDs and access key hashes must be unique')
        seen_ids.add(row['tenant_id'])
        seen_keys.add(row['api_key_sha256'])
        normalized.append(row)
    return tuple(normalized)


def directory_mode():
    value = os.getenv('CLOUDSAVER_DIRECTORY_MODE', 'registry')
    if value not in ('registry', 'cutover'):
        raise ValueError('CLOUDSAVER_DIRECTORY_MODE must be registry or cutover')
    return value


def key_verifier():
    value = os.getenv('CLOUDSAVER_KEY_VERIFIER', 'local')
    if value not in ('local', 'shadow', 'identity'):
        raise ValueError('CLOUDSAVER_KEY_VERIFIER must be local, shadow or identity')
    if directory_mode() == 'cutover' and value != 'identity':
        raise ValueError('CLOUDSAVER_DIRECTORY_MODE=cutover requires CLOUDSAVER_KEY_VERIFIER=identity')
    return value


@dataclass(frozen=True)
class Settings:
    mode: str
    database: str
    bootstrap_tenants: tuple
    database_url: str | None = None
    registry: object = field(default=None, compare=False, repr=False)

    @property
    def tenants(self):
        """Active tenants; the registry is authoritative when it is enabled."""
        if self.registry is None:
            return tuple(t for t in self.bootstrap_tenants if t.get('active', True))
        return tuple(t for t in self.registry.all() if t['active'])

    @classmethod
    def load(cls):
        mode = os.getenv('CLOUDSAVER_MODE', 'azure')
        if mode != 'azure':
            raise ValueError('CLOUDSAVER_MODE must be azure')
        database_url = os.getenv('CLOUDSAVER_DATABASE_URL') or None
        use_registry = os.getenv('CLOUDSAVER_TENANT_REGISTRY', 'env') == 'database'
        if use_registry and not database_url:
            raise ValueError('CLOUDSAVER_TENANT_REGISTRY=database requires CLOUDSAVER_DATABASE_URL')
        cutover = directory_mode() == 'cutover'
        if cutover and not use_registry:
            raise ValueError('CLOUDSAVER_DIRECTORY_MODE=cutover requires CLOUDSAVER_TENANT_REGISTRY=database')
        # After cutover the platform directory owns workspaces; the bootstrap seed is ignored.
        tenants = () if cutover else bootstrap_tenants(required=not use_registry)
        registry = None
        if use_registry:
            from app.tenant_registry import registry_for
            registry = registry_for(database_url, tenants)
        database = os.getenv('CLOUDSAVER_DB', 'data/cloudsaver.sqlite3')
        return cls(mode, database, tenants, database_url, registry)
