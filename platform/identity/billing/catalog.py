"""Plan entitlements: the schema, its validation and the seed catalog.

The seed copies CloudSaver's former TIER_LIMITS (Starter, Growth, Enterprise) and adds the key-management
limits that stay inside the platform. Migration i0002 seeds the same values; a test keeps them equal.
"""
from identity.domain import IdentityError

PROVIDERS = ('azure', 'aws', 'gcp', 'kubernetes')
FREQUENCIES = ('manual', 'daily', 'hourly')
# Sent to CloudSaver in the verify and directory plan block.
CLOUDSAVER_KEYS = ('max_subscriptions', 'max_resources_per_scan', 'allowed_scan_frequencies', 'can_export_terraform',
                   'can_use_keyvault', 'can_dispatch_automated_alerts', 'retention_days', 'allowed_providers', 'can_use_ai_advisory')
# Enforced by identity-service only.
PLATFORM_KEYS = ('max_workspaces', 'max_active_keys_per_workspace', 'max_key_lifetime_days')
ENTITLEMENT_KEYS = CLOUDSAVER_KEYS + PLATFORM_KEYS
LABELS = {
    'max_subscriptions': 'Cloud scopes per workspace', 'max_resources_per_scan': 'Resources per scan',
    'allowed_scan_frequencies': 'Scan frequencies', 'can_export_terraform': 'Terraform review',
    'can_use_keyvault': 'Key Vault', 'can_dispatch_automated_alerts': 'Automatic alerts',
    'retention_days': 'Retention (days)', 'allowed_providers': 'Cloud providers',
    'max_workspaces': 'Workspaces per customer', 'max_active_keys_per_workspace': 'Active keys per workspace',
    'max_key_lifetime_days': 'Maximum key lifetime (days)',
    'can_use_ai_advisory': 'AI advisory',
}
INTEGERS = {'max_subscriptions': (0, 1_000_000), 'max_resources_per_scan': (1, 10_000_000), 'retention_days': (1, 3650),
            'max_workspaces': (1, 10_000), 'max_active_keys_per_workspace': (1, 20), 'max_key_lifetime_days': (1, 365)}
BOOLEANS = ('can_export_terraform', 'can_use_keyvault', 'can_dispatch_automated_alerts', 'can_use_ai_advisory')

SEED_PLANS = (
    {'code': 'STARTER', 'name': 'Starter', 'description': 'Manual scans for small teams.',
     'entitlements': {'max_subscriptions': 2, 'max_resources_per_scan': 250, 'allowed_scan_frequencies': ['manual'],
                      'can_export_terraform': False, 'can_use_keyvault': False, 'can_dispatch_automated_alerts': False, 'can_use_ai_advisory': False,
                      'retention_days': 7, 'allowed_providers': list(PROVIDERS), 'max_workspaces': 3,
                      'max_active_keys_per_workspace': 5, 'max_key_lifetime_days': 365}},
    {'code': 'GROWTH', 'name': 'Growth', 'description': 'Daily scans, Terraform review and automatic alerts.',
     'entitlements': {'max_subscriptions': 10, 'max_resources_per_scan': 2500,
                      'allowed_scan_frequencies': ['manual', 'daily'], 'can_export_terraform': True,
                      'can_use_keyvault': False, 'can_dispatch_automated_alerts': True, 'retention_days': 90, 'can_use_ai_advisory': True,
                      'allowed_providers': list(PROVIDERS), 'max_workspaces': 10, 'max_active_keys_per_workspace': 10,
                      'max_key_lifetime_days': 365}},
    {'code': 'ENTERPRISE', 'name': 'Enterprise', 'description': 'Hourly scans, Key Vault and long retention.',
     'entitlements': {'max_subscriptions': 1000, 'max_resources_per_scan': 100000,
                      'allowed_scan_frequencies': ['manual', 'daily', 'hourly'], 'can_export_terraform': True,
                      'can_use_keyvault': True, 'can_dispatch_automated_alerts': True, 'retention_days': 365, 'can_use_ai_advisory': True,
                      'allowed_providers': list(PROVIDERS), 'max_workspaces': 100, 'max_active_keys_per_workspace': 20,
                      'max_key_lifetime_days': 365}},
)
SEED_SETTINGS = {'default_plan_code': 'STARTER', 'default_grace_days': 14, 'lapsed_action': 'downgrade',
                 'lapsed_plan_code': 'STARTER', 'default_manage_billing_url': None, 'require_subscription_for_keys': True}


def _subset(key, value, allowed, *, require=None):
    if (not isinstance(value, list) or not value or any(v not in allowed for v in value)
            or len(set(value)) != len(value) or (require and require not in value)):
        extra = f' and include {require}' if require else ''
        raise IdentityError(f'{LABELS[key]} must be one or more of {", ".join(allowed)}{extra}.')
    return [v for v in allowed if v in value]


def validate_entitlements(value, *, partial=False):
    """Return normalized entitlements in canonical key order. Unknown keys are rejected."""
    if not isinstance(value, dict):
        raise IdentityError('Entitlements must be an object.')
    if not partial:
        value = dict(value)
        value.setdefault('can_use_ai_advisory', False)
    unknown = sorted(set(value) - set(ENTITLEMENT_KEYS))
    if unknown:
        raise IdentityError(f'Remove unknown entitlements: {", ".join(unknown)}.')
    missing = [k for k in ENTITLEMENT_KEYS if k not in value]
    if missing and not partial:
        raise IdentityError(f'Include every entitlement. Missing: {", ".join(missing)}.')
    result = {}
    for key in ENTITLEMENT_KEYS:
        if key not in value:
            continue
        item = value[key]
        if key in INTEGERS:
            low, high = INTEGERS[key]
            if not isinstance(item, int) or isinstance(item, bool) or not low <= item <= high:
                raise IdentityError(f'{LABELS[key]} must be a whole number from {low:,} to {high:,}.')
        elif key in BOOLEANS:
            if not isinstance(item, bool):
                raise IdentityError(f'{LABELS[key]} must be on or off.')
        elif key == 'allowed_scan_frequencies':
            item = _subset(key, item, FREQUENCIES, require='manual')
        else:
            item = _subset(key, item, PROVIDERS)
        result[key] = item
    return result


def merged(plan_entitlements, overrides=None):
    """Plan entitlements overlaid by subscription overrides, with the source of each value."""
    overrides = overrides or {}
    values = {k: (overrides[k] if k in overrides else plan_entitlements[k]) for k in ENTITLEMENT_KEYS if k in plan_entitlements or k in overrides}
    sources = {k: 'override' if k in overrides else 'plan' for k in values}
    return values, sources
