"""Provider and scope narrowing for workspace keys limited to some cloud providers or cloud scopes."""
from contextvars import ContextVar

from fastapi import HTTPException

from app.route_inventory import classify

LABELS = {'azure': 'Azure', 'aws': 'AWS', 'gcp': 'Google Cloud', 'kubernetes': 'Kubernetes'}
SCOPE_KEYS = {'azure': 'subscription_ids', 'aws': 'aws_accounts', 'gcp': 'gcp_projects', 'kubernetes': 'kubernetes_clusters'}
SCOPE_IDENTITY = {'aws_accounts': 'account_id', 'gcp_projects': 'project_id', 'kubernetes_clusters': 'cluster_id'}
ALL_PROVIDERS_REQUIRED = "This workspace key doesn't include all providers."
ALL_SCOPES_REQUIRED = "This workspace key is limited to some cloud scopes."

# (allowed providers, strict, scope limits). None means the principal sees every configured provider and scope.
access = ContextVar('cloudsaver_provider_access', default=None)


def denied(provider):
    return HTTPException(403, f"This workspace key doesn't include {LABELS.get(provider, provider)}.")


def narrow(tenant, allowed):
    """Effective workspace: scope lists of providers outside the grant are emptied."""
    allowed = set(allowed)
    return dict(tenant, **{key: (tenant.get(key, []) if provider in allowed else [])
                           for provider, key in SCOPE_KEYS.items()})


def scope_id(key, item):
    field = SCOPE_IDENTITY.get(key)
    return item if field is None else item.get(field)


def restrict(tenant, limits):
    """Effective workspace for a scope-limited key: only the listed scopes remain for limited providers."""
    changes = {}
    for provider, ids in (limits or {}).items():
        key = SCOPE_KEYS.get(provider)
        if key:
            changes[key] = [item for item in tenant.get(key, []) if scope_id(key, item) in set(ids)]
    return dict(tenant, **changes)


def require_providers(tenant, providers):
    allowed = tenant.get('allowed_providers')
    if allowed is None:
        return
    for provider in providers:
        if provider not in allowed:
            raise denied(provider)


def enforce_route(method, path, tenant, configured):
    """Called by tenant_dependency before the handler; sets the request's provider and scope filter."""
    allowed = tenant.get('allowed_providers')
    limits = tenant.get('scope_restrictions') or None
    if limits is None and (allowed is None or set(configured) <= set(allowed)):
        access.set(None)
        return
    kind = classify(method, path)
    message = ALL_PROVIDERS_REQUIRED if limits is None else ALL_SCOPES_REQUIRED
    if kind is None or kind in ('public', 'full_scope'):
        raise HTTPException(403, message)
    if isinstance(kind, tuple):
        require_providers(tenant, kind)
    providers = frozenset(configured if allowed is None else allowed)
    scopes = {p: frozenset(ids) for p, ids in limits.items()} if limits else None
    access.set((providers, kind == 'scan_write', scopes))


def scan_providers(scan):
    providers = set(scan.get('cloud_providers') or ['azure'])
    providers |= {f.get('cloud_provider', 'azure') for f in scan.get('findings', [])}
    return providers


def finding_in_scope(finding, scopes):
    provider = finding.get('cloud_provider', 'azure')
    if not scopes or provider not in scopes:
        return True
    value = finding.get('subscription_id') if provider == 'azure' else finding.get('scope_id')
    return str(value or '').lower() in {s.lower() for s in scopes[provider]}


def filter_scan(scan, allowed, strict=False, scopes=None):
    if scan is None:
        return None
    providers = scan_providers(scan)
    if strict and not providers <= allowed:
        return None
    if not providers & allowed:
        return None
    findings = scan.get('findings', [])
    in_scope = [f for f in findings if f.get('cloud_provider', 'azure') in allowed and finding_in_scope(f, scopes)]
    if strict and scopes and len(in_scope) != len([f for f in findings if f.get('cloud_provider', 'azure') in allowed]):
        return None
    if providers <= allowed and len(in_scope) == len(findings):
        return scan
    waste = [f.get('estimated_monthly_waste_usd') for f in in_scope]
    realizable = [(f.get('cost_attribution') or {}).get('realizable_savings_usd') for f in in_scope]
    return dict(
        scan, findings=in_scope, total_items_found=len(in_scope),
        cloud_providers=sorted(p for p in (scan.get('cloud_providers') or ['azure']) if p in allowed),
        subscriptions_scanned=scan.get('subscriptions_scanned', 0) if 'azure' in allowed else 0,
        total_monthly_waste_usd=round(sum(waste), 2) if in_scope and all(v is not None for v in waste) else None,
        realizable_monthly_savings_usd=round(sum(realizable), 2) if in_scope and all(v is not None for v in realizable) else None,
        provider_filtered=True, scope_filtered=bool(scopes))


def _filter(scan, current, strict=None):
    providers, default_strict = current[0], current[1]
    scopes = current[2] if len(current) > 2 else None
    return filter_scan(scan, providers, default_strict if strict is None else strict, scopes)


class ScopedStore:
    """Read-side wrapper; writes and other attributes go straight to the underlying store."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def get(self, tenant_id, scan_id):
        scan = self.inner.get(tenant_id, scan_id)
        current = access.get()
        return scan if current is None else _filter(scan, current)

    def list(self, tenant_id, limit=50):
        scans = self.inner.list(tenant_id, limit)
        current = access.get()
        if current is None:
            return scans
        return [s for s in (_filter(scan, current, strict=False) for scan in scans) if s is not None]
