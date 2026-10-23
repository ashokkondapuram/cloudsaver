"""Workspace analysis rule overrides from identity-service (optional)."""
import logging

logger = logging.getLogger('cloudsaver.analysis.rules')


def enabled_rule_ids_for_tenant(tenant_id: str) -> set[str] | None:
    """Return enabled rule ids, or None when identity is unavailable (scan all rules)."""
    from app.identity_client import IdentityUnavailable, shared_client

    try:
        client = shared_client()
    except RuntimeError:
        return None
    try:
        response = client.get(f'/internal/v1/tenants/{tenant_id}/analysis-rules/effective', timeout=3.0)
    except IdentityUnavailable:
        logger.warning('Identity unavailable; using full rule catalog for tenant=%s', tenant_id)
        return None
    if response.status_code != 200:
        logger.warning('Effective rules request failed status=%s tenant=%s', response.status_code, tenant_id)
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    ids = payload.get('enabled_rule_ids')
    if not isinstance(ids, list):
        return None
    return {str(r) for r in ids}
