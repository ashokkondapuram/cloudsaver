"""Workspace analysis rule overrides from identity-service (optional)."""
import logging

logger = logging.getLogger('cloudsaver.analysis.rules')


def policy_for_tenant(tenant_id: str) -> dict | None:
    """Return the frozen policy input; identity-managed callers fail closed on None."""
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
    if any(not isinstance(value, str) for value in ids):
        return None
    return payload


def enabled_rule_ids_for_tenant(tenant_id: str) -> set[str] | None:
    policy = policy_for_tenant(tenant_id)
    return set(policy['enabled_rule_ids']) if policy is not None else None
