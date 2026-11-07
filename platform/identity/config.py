"""Platform environment: PLATFORM_* names, with the CLOUDSAVER_* names accepted during 1.0.x."""
import hashlib
import logging
import os
from pathlib import Path

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


def operator_key_sha256():
    """Digest for operator_key auth: env digest, else SHA-256 of a mounted key file or plaintext env."""
    expected = (env('OPERATOR_KEY_SHA256') or '').strip().lower()
    if len(expected) == 64:
        return expected
    file_path = (env('OPERATOR_ACCESS_KEY_FILE') or '').strip()
    if file_path:
        try:
            line = Path(file_path).read_text(encoding='utf-8').strip().splitlines()[0].strip()
            if line:
                return hashlib.sha256(line.encode()).hexdigest()
        except OSError:
            pass
    plain = (env('OPERATOR_ACCESS_KEY') or '').strip()
    if plain:
        return hashlib.sha256(plain.encode()).hexdigest()
    return ''


def billing_session_flags():
    """Portal session fields; driven only by platform/.env (PLATFORM_BILLING_*), not CloudSaver."""
    enabled = flag('BILLING_ENABLED')
    provider = env('BILLING_PROVIDER', 'manual') if enabled else 'manual'
    if provider not in ('manual', 'stripe'):
        provider = 'manual'
    return {'billing_enabled': enabled, 'billing_provider': provider}
