"""CloudSaver stack integration toggles (platform UI, env fallback, directory projection)."""
import os
import re

INTEGRATION_KEYS = (
    'live_evidence_enabled',
    'azure_arm_detail_enabled',
    'azure_arm_detail_max',
    'live_evidence_max_resources',
    'default_billing_currency',
    'auto_billing_sync',
    'delivery_enabled',
    'observability_sync',
)

BOOL_KEYS = {
    'live_evidence_enabled',
    'azure_arm_detail_enabled',
    'auto_billing_sync',
    'delivery_enabled',
    'observability_sync',
}
INT_KEYS = {'azure_arm_detail_max', 'live_evidence_max_resources'}


def _flag(name, default='false'):
    return os.getenv(name, default).lower() == 'true'


def _int(name, default):
    try:
        return int(os.getenv(name, str(default)).strip() or str(default))
    except ValueError:
        return default


def env_defaults():
    currency = (os.getenv('CLOUDSAVER_DEFAULT_BILLING_CURRENCY') or 'USD').upper()
    if not re.fullmatch(r'[A-Z]{3}', currency):
        currency = 'USD'
    return {
        'live_evidence_enabled': _flag('CLOUDSAVER_LIVE_EVIDENCE_ENABLED'),
        'azure_arm_detail_enabled': _flag('CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED', 'true'),
        'azure_arm_detail_max': _int('CLOUDSAVER_AZURE_ARM_DETAIL_MAX', 0),
        'live_evidence_max_resources': _int('CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES', 0),
        'default_billing_currency': currency,
        'auto_billing_sync': _flag('CLOUDSAVER_AUTO_BILLING_SYNC', 'true'),
        'delivery_enabled': _flag('CLOUDSAVER_DELIVERY_ENABLED'),
        'observability_sync': _flag('CLOUDSAVER_OBSERVABILITY_SYNC', 'true'),
    }


def normalize_cloudsaver_integration(value, *, partial=False):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Unknown CloudSaver integration setting')
    unknown = set(value) - set(INTEGRATION_KEYS)
    if unknown:
        raise ValueError('Unknown CloudSaver integration setting')
    result = {}
    for key, raw in value.items():
        if raw is None:
            continue
        if key in BOOL_KEYS:
            if not isinstance(raw, bool):
                raise ValueError('CloudSaver integration switches must be on or off.')
            result[key] = raw
        elif key in INT_KEYS:
            if type(raw) is not int or not 0 <= raw <= 50000:
                raise ValueError('Enter a resource limit from 0 to 50000. Use 0 for no cap.')
            result[key] = raw
        elif key == 'default_billing_currency':
            if raw == '':
                result[key] = None
                continue
            code = str(raw).upper()
            if not re.fullmatch(r'[A-Z]{3}', code):
                raise ValueError('Enter a three-letter currency code such as USD.')
            result[key] = code
    return result


def merge_cloudsaver_integration(current, patch):
    merged = dict(current or {})
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _platform_value(platform_value, key, env):
    if platform_value and key in platform_value and platform_value[key] is not None:
        return platform_value[key], 'platform'
    if key in env and env[key] is not None:
        return env[key], 'environment'
    return None, 'unset'


def effective_cloudsaver_integration(platform_value, env=None):
    env = env or env_defaults()
    return {key: {'value': _platform_value(platform_value or {}, key, env)[0],
                   'source': _platform_value(platform_value or {}, key, env)[1]}
            for key in INTEGRATION_KEYS}
