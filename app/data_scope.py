"""SQL predicates for coarse governance scope; unlabelled legacy rows fail closed."""
def restricted(tenant):
    return tenant.get('allowed_providers') is not None or bool(tenant.get('scope_restrictions'))

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
