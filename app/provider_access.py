"""Provider narrowing for workspace keys limited to some cloud providers."""
from contextvars import ContextVar

from fastapi import HTTPException

from app.route_inventory import classify

LABELS = {'azure': 'Azure', 'aws': 'AWS', 'gcp': 'Google Cloud', 'kubernetes': 'Kubernetes'}
SCOPE_KEYS = {'azure': 'subscription_ids', 'aws': 'aws_accounts', 'gcp': 'gcp_projects', 'kubernetes': 'kubernetes_clusters'}
ALL_PROVIDERS_REQUIRED = "This workspace key doesn't include all providers."

# (allowed providers, strict). None means the principal sees every configured provider.
access = ContextVar('cloudsaver_provider_access', default=None)


def denied(provider):
    return HTTPException(403, f"This workspace key doesn't include {LABELS.get(provider, provider)}.")


def narrow(tenant, allowed):
    """Effective workspace: scope lists of providers outside the grant are emptied."""
    allowed = set(allowed)
    return dict(tenant, **{key: (tenant.get(key, []) if provider in allowed else [])
                           for provider, key in SCOPE_KEYS.items()})


def require_providers(tenant, providers):
    allowed = tenant.get('allowed_providers')
    if allowed is None:
        return
    for provider in providers:
        if provider not in allowed:
            raise denied(provider)


def enforce_route(method, path, tenant, configured):
    """Called by tenant_dependency before the handler; sets the request's provider filter."""
    allowed = tenant.get('allowed_providers')
    if allowed is None or set(configured) <= set(allowed):
        access.set(None)
        return
    kind = classify(method, path)
    if kind is None or kind == 'public':
        raise HTTPException(403, ALL_PROVIDERS_REQUIRED)
    if kind == 'full_scope':
        raise HTTPException(403, ALL_PROVIDERS_REQUIRED)
    if isinstance(kind, tuple):
        require_providers(tenant, kind)
    access.set((frozenset(allowed), kind == 'scan_write'))


def scan_providers(scan):
    providers = set(scan.get('cloud_providers') or ['azure'])
    providers |= {f.get('cloud_provider', 'azure') for f in scan.get('findings', [])}
    return providers


def filter_scan(scan, allowed, strict=False):
    if scan is None:
        return None
    providers = scan_providers(scan)
    if strict and not providers <= allowed:
        return None
    if not providers & allowed:
        return None
    if providers <= allowed:
        return scan
    findings = [f for f in scan.get('findings', []) if f.get('cloud_provider', 'azure') in allowed]
    waste = [f.get('estimated_monthly_waste_usd') for f in findings]
    realizable = [(f.get('cost_attribution') or {}).get('realizable_savings_usd') for f in findings]
    return dict(
        scan, findings=findings, total_items_found=len(findings),
        cloud_providers=sorted(p for p in (scan.get('cloud_providers') or ['azure']) if p in allowed),
        subscriptions_scanned=scan.get('subscriptions_scanned', 0) if 'azure' in allowed else 0,
        total_monthly_waste_usd=round(sum(waste), 2) if findings and all(v is not None for v in waste) else None,
        realizable_monthly_savings_usd=round(sum(realizable), 2) if findings and all(v is not None for v in realizable) else None,
        provider_filtered=True)


class ScopedStore:
    """Read-side wrapper; writes and other attributes go straight to the underlying store."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def get(self, tenant_id, scan_id):
        scan = self.inner.get(tenant_id, scan_id)
        current = access.get()
        return scan if current is None else filter_scan(scan, current[0], current[1])

    def list(self, tenant_id, limit=50):
        scans = self.inner.list(tenant_id, limit)
        current = access.get()
        if current is None:
            return scans
        return [s for s in (filter_scan(scan, current[0]) for scan in scans) if s is not None]
