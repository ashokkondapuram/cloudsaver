"""One-time, idempotent import of registry workspaces and legacy key digests into token-db.

Imported keys keep working unchanged: they receive every role and every provider and expire at the
legacy deadline (cutover + 90 days unless CLOUDSAVER_LEGACY_KEY_DEADLINE is set). Re-running the import
skips workspaces and keys that already exist, even after a key was upgraded to HMAC on first use.
"""
import logging
import os
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from identity import keys as keyfmt
from identity.domain import SCOPE_KEYS, parse_time, utcnow

logger = logging.getLogger('cloudsaver.identity.import')
ACTOR = {'actor': 'registry-import', 'actor_type': 'system'}
IMPORTED_NAME = 'Imported workspace key'


def customer_id_for(tenant_id):
    return str(uuid5(NAMESPACE_URL, 'cloudsaver:organization:' + tenant_id))


def legacy_deadline(now=None):
    raw = os.getenv('CLOUDSAVER_LEGACY_KEY_DEADLINE')
    return parse_time(raw, 'Legacy key deadline') if raw else (now or utcnow()) + timedelta(days=90)


def registry_rows(url):
    """Rows read through the read-only cloudsaver_registry_export role."""
    import psycopg
    with psycopg.connect(url, connect_timeout=5) as db:
        rows = db.execute('SELECT tenant_id, name, plan_tier, api_key_sha256, active, config '
                          'FROM public.tenant_registry ORDER BY tenant_id').fetchall()
        platform = db.execute('SELECT settings FROM public.platform_settings WHERE id=1').fetchone()
    tenants = [dict(row[5] or {}, tenant_id=str(row[0]), name=row[1], plan_tier=row[2],
                    api_key_sha256=row[3].strip() if row[3] else None, active=row[4]) for row in rows]
    return tenants, (platform[0] if platform else None)


def env_rows():
    from app.config import bootstrap_tenants
    return [dict(t) for t in bootstrap_tenants(required=False)]


def import_directory(service, tenants, source, *, platform=None, deadline=None, entra=False):
    """Returns counts; never prints or logs key material."""
    now = service.now()
    deadline = deadline or legacy_deadline(now)
    counts = {'customers': 0, 'workspaces': 0, 'keys': 0, 'skipped_keys': 0}
    for tenant in tenants:
        tid = tenant['tenant_id']
        customer_id = customer_id_for(tid)
        with service.store.transaction() as tx:
            if not tx.get_customer(customer_id):
                tx.insert_customer({'id': customer_id, 'name': tenant['name'][:120], 'status': 'active', 'notes': None,
                                    'version': 1, 'created_at': now, 'created_by': ACTOR['actor'], 'updated_at': now,
                                    'updated_by': ACTOR['actor'], 'deleted_at': None})
                service._event(tx, ACTOR, 'customer_created', details={'customer_id': customer_id, 'name': tenant['name'][:120],
                                                                      'source': source})
                counts['customers'] += 1
            exists = tx.get_workspace(tid) is not None
        if not exists:
            service.create_workspace(
                {'tenant_id': tid, 'customer_id': customer_id, 'name': tenant['name'], 'plan_tier': tenant['plan_tier'],
                 'identity': tenant.get('identity') or {}}, ACTOR,
                scopes={key: tenant.get(key, []) for key in SCOPE_KEYS.values()},
                status='active' if tenant.get('active', True) else 'suspended')
            counts['workspaces'] += 1
        digest = tenant.get('api_key_sha256')
        if not digest:
            continue
        fingerprint = service.peppers.fingerprint(digest)
        with service.store.transaction() as tx:
            if tx.key_by_fingerprint(fingerprint) or tx.key_by_legacy(digest):
                counts['skipped_keys'] += 1
                continue
            # Entra deployments seed random placeholder digests that no caller holds; keep them revoked.
            row = {'id': str(uuid4()), 'key_id': keyfmt.legacy_key_id(), 'tenant_id': tid, 'name': IMPORTED_NAME,
                   'roles': ['TenantAdmin', 'BillingAdmin', 'Viewer'], 'all_providers': True, 'allowed_providers': [],
                   'scope_restrictions': None, 'format': 'legacy', 'hash_scheme': 'sha256_legacy', 'secret_digest': None,
                   'pepper_version': None, 'legacy_sha256': digest, 'legacy_fingerprint': fingerprint,
                   'created_at': now, 'created_by': ACTOR['actor'], 'expires_at': deadline,
                   'revoked_at': now if entra else None, 'revoked_by': ACTOR['actor'] if entra else None,
                   'revoke_reason': 'Entra placeholder' if entra else None, 'rotated_from': None, 'rotates_out_at': None,
                   'last_used_at': None, 'last_used_ip': None, 'source': source, 'version': 1}
            tx.insert_key(row)
            service._event(tx, ACTOR, 'imported', tid, row['key_id'],
                           {'name': IMPORTED_NAME, 'source': source, 'expires_at': deadline.isoformat()})
            counts['keys'] += 1
    if platform:
        current = service.get_platform()
        changes = {k: platform[k] for k in ('scheduled_scans_enabled', 'automated_alerts_enabled')
                   if k in platform and platform[k] != current[k]}
        if changes:
            service.update_platform(dict(changes, version=current['version']), ACTOR)
    return counts


def main():
    from identity.app import build_service
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
    from identity.redaction import install_log_redaction
    install_log_redaction()
    service = build_service()
    entra = os.getenv('CLOUDSAVER_AUTH_MODE') == 'entra'
    url = os.getenv('CLOUDSAVER_REGISTRY_EXPORT_URL')
    total = {}
    if url:
        tenants, platform = registry_rows(url)
        total['registry'] = import_directory(service, tenants, 'registry_import', platform=platform, entra=entra)
    seen = {t['tenant_id'] for t in (tenants if url else [])}
    env = [t for t in env_rows() if t['tenant_id'] not in seen]
    if env:
        total['env'] = import_directory(service, env, 'env_import', entra=entra)
    for source, counts in total.items():
        logger.info('Import from %s: %s', source, ', '.join(f'{k}={v}' for k, v in counts.items()))
    if not total:
        logger.info('Nothing to import')


if __name__ == '__main__':
    main()
