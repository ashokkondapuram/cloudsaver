"""Platform environment: PLATFORM_* names, with the CLOUDSAVER_* names accepted during 1.0.x."""
import logging
import os

logger = logging.getLogger('platform.identity')
_warned = set()


def env(name, default=None, *, legacy=None):
    """PLATFORM_<name>, else the deprecated legacy name (CLOUDSAVER_<name> unless given). Empty means unset."""
    value = os.getenv('PLATFORM_' + name)
    if value:
        return value
    old = legacy or 'CLOUDSAVER_' + name
    value = os.getenv(old)
    if value:
        if old not in _warned:
            _warned.add(old)
            # Name only: the value may be a secret.
            logger.warning('%s is deprecated. Rename it to PLATFORM_%s.', old, name)
        return value
    return default


def flag(name, default=False):
    value = env(name)
    return default if value is None else value.strip().lower() == 'true'


def integer(name, default, low, high):
    value = int(env(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f'PLATFORM_{name} is outside its supported range')
    return value


def billing_session_flags():
    """Portal session fields; driven only by platform/.env (PLATFORM_BILLING_*), not CloudSaver."""
    enabled = flag('BILLING_ENABLED')
    provider = env('BILLING_PROVIDER', 'manual') if enabled else 'manual'
    if provider not in ('manual', 'stripe'):
        provider = 'manual'
    return {'billing_enabled': enabled, 'billing_provider': provider}
