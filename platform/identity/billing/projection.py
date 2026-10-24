"""Directory and verify plan blocks from billing state (CloudSaver entitlement projection)."""
from identity.billing.catalog import CLOUDSAVER_KEYS, SEED_PLANS, merged, validate_entitlements
from identity.billing.domain import billing_state
from identity.config import flag
from identity.domain import iso


def _seed_entitlements(code, stored):
    base = next((p['entitlements'] for p in SEED_PLANS if p['code'] == code), {})
    return validate_entitlements({**base, **(stored or {})})


def workspace_plan_block(tx, workspace, customer, now):
    """Plan block for directory snapshots and verify grants."""
    plans = {p['code']: p for p in tx.list_plans()}
    settings = tx.get_billing_settings()
    sub = tx.latest_subscription(customer['id']) if flag('BILLING_ENABLED') else None
    state, grace_end = billing_state(sub, now) if flag('BILLING_ENABLED') else ('active', None)
    plan_code = sub['plan_code'] if sub else workspace['plan_tier']
    lapsed = flag('BILLING_ENABLED') and state in ('lapsed', 'none')
    if lapsed:
        plan_code = settings['lapsed_plan_code']
    if plan_code not in plans:
        plan_code = workspace['plan_tier']
    plan_row = plans.get(plan_code, {})
    plan_ent = _seed_entitlements(plan_code, (plan_row or {}).get('entitlements'))
    overrides = ((sub or {}).get('entitlement_overrides') or {}) if not lapsed else {}
    values, _ = merged(plan_ent, overrides if overrides else None)
    cloud = {k: values[k] for k in CLOUDSAVER_KEYS if k in values}
    if flag('BILLING_ENABLED'):
        state, grace_end = billing_state(sub, now)
    else:
        state, grace_end = 'active', None
    manage = customer.get('manage_billing_url') or settings.get('default_manage_billing_url')
    version = int(workspace.get('entitlements_version') or 1)
    return {
        **({'access_suspended': True} if lapsed and settings['lapsed_action'] == 'suspend' else {}),
        'code': plan_code,
        'name': (plan_row or {}).get('name') or plan_code,
        'billing_state': state,
        'current_period_end': iso(sub['current_period_end']) if sub else None,
        'grace_ends_at': iso(grace_end) if grace_end else None,
        'subscription_plan_name': (plans.get(sub['plan_code']) or {}).get('name') if sub else None,
        'entitlements': cloud,
        'entitlements_version': version,
        'manage_billing_url': manage,
    }
