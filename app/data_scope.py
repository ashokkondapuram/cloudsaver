"""SQL predicates for coarse governance scope; unlabelled legacy rows fail closed."""
from uuid import UUID


def restricted(tenant):
    return tenant.get('allowed_providers') is not None or bool(tenant.get('scope_restrictions'))


def resource_visible(tenant, provider, scope_id):
    """Governance/outcomes rows keyed by provider and scope."""
    return metadata_visible(tenant, {'provider': provider, 'scope_id': scope_id})


def metadata_visible(tenant, metadata):
    """Provider-scoped keys only see labelled AI rows inside their grant."""
    if not restricted(tenant):
        return True
    provider = metadata.get('source_provider') or metadata.get('provider')
    scope = metadata.get('scope_id')
    if not provider:
        return False
    allowed = tenant.get('allowed_providers')
    if allowed is not None and provider not in allowed:
        return False
    limits = (tenant.get('scope_restrictions') or {}).get(provider)
    if limits is not None:
        if not scope:
            return False
        return str(scope).lower() in {value.lower() for value in limits}
    if provider == 'azure':
        if not scope:
            return False
        try:
            scope = str(UUID(scope))
        except ValueError:
            return False
        return scope in tenant.get('subscription_ids', [])
    if provider == 'aws':
        return scope in {account['account_id'] for account in tenant.get('aws_accounts', [])}
    if provider == 'gcp':
        return scope in {project['project_id'] for project in tenant.get('gcp_projects', [])}
    return provider == 'kubernetes'


def scan_visible(store, tenant, scan_id):
    """True when the scan exists for this tenant under the tenant's provider grant."""
    if not restricted(tenant):
        return True
    inner = getattr(store, 'inner', store)
    scan = inner.get(tenant['tenant_id'], str(scan_id))
    if scan is None:
        return False
    from app.provider_access import filter_scan
    allowed = tenant.get('allowed_providers')
    providers = frozenset(allowed) if allowed is not None else frozenset()
    limits = tenant.get('scope_restrictions') or None
    scopes = {provider: frozenset(ids) for provider, ids in limits.items()} if limits else None
    return filter_scan(scan, providers, strict=False, scopes=scopes) is not None


def predicate(tenant,provider='cloud_provider',scope='scope_id'):
    if not restricted(tenant):return '',[]
    allowed=tenant.get('allowed_providers')
    providers=['azure','aws','gcp','kubernetes'] if allowed is None else allowed
    parts=[];args=[]
    for value in providers:
        limits=(tenant.get('scope_restrictions') or {}).get(value)
        if limits is not None and not limits:continue
        clause=provider+'=%s';values=[value]
        if limits is not None:
            clause+=' AND LOWER('+scope+') IN ('+','.join('%s' for _ in limits)+')'
            values += [s.lower() for s in limits]
        else:clause+=' AND '+scope+' IS NOT NULL'
        parts.append('('+clause+')');args+=values
    return ' AND ('+(' OR '.join(parts) or '1=0')+')',args
