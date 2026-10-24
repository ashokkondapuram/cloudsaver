"""Stable audit identities and provider/scope visibility shared by core services."""
import hashlib

def actor(tenant):
    return hashlib.sha256((tenant.get('subject_id') or tenant.get('user_id') or tenant.get('key_id') or tenant['tenant_id']).encode()).hexdigest()


def visible(case,tenant):
    from app.focus import authorized
    from app.provider_access import finding_in_scope
    if tenant.get('allowed_providers') is not None and case['provider'] not in tenant['allowed_providers']:return False
    limits=tenant.get('scope_restrictions')
    return finding_in_scope({'cloud_provider':case['provider'],'scope_id':case['scope_id'],'subscription_id':case['scope_id']},limits)
