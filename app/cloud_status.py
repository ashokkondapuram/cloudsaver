"""Workspace cloud readiness: scopes, billing bindings, and read-only access probes."""
from app.access_probe import run_probe
from app.cloud_identity import identity_mode


def billing_scope_rows(tenant):
    from app.collectors.billing_sync import bindings
    from app.focus import authorized

    try:
        configured = bindings(tenant)
    except Exception as exc:
        return {'status': 'error', 'message': str(exc), 'scopes': []}
    rows = []
    for binding in configured:
        scope_id = binding.get('scope_id', '')
        rows.append({
            'provider': binding['provider'],
            'scope_id': scope_id,
            'authorized_for_workspace': authorized(binding['provider'], scope_id, tenant),
        })
    return {'status': 'ok', 'scopes': rows}


def azure_session_hint():
    if identity_mode() != 'developer':
        return {'mode': identity_mode(), 'developer_sign_in': None}
    try:
        from app.cloud_identity import platform_credential
        credential = platform_credential()
        try:
            credential.get_token('https://management.azure.com/.default')
            return {'mode': 'developer', 'developer_sign_in': 'ready'}
        finally:
            credential.close()
    except Exception:
        return {'mode': 'developer', 'developer_sign_in': 'run_az_login'}


def cloud_status(tenant, platform=None):
    stored = dict(tenant)
    return {
        'workspace_id': tenant.get('tenant_id'),
        'identity_mode': identity_mode(),
        'subscription_ids': list(stored.get('subscription_ids') or []),
        'identity': stored.get('identity') or {},
        'azure_session': azure_session_hint(),
        'billing': billing_scope_rows(stored),
        'access': run_probe(stored, platform),
    }
