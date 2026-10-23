"""Workspace key format, generation and peppered hashing.

Plaintext keys exist only in the issue/rotate response and in the caller's request.
Only HMAC digests (or, for not-yet-upgraded imports, the legacy SHA-256) are stored.
"""
import hashlib
import hmac
import re
import secrets
import string

CROCKFORD = '0123456789abcdefghjkmnpqrstvwxyz'
BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase
V1 = re.compile(r'^cs_(live|test)_([0-9a-hjkmnp-tv-z]{12})_[0-9A-Za-z]{43}$')
# setup_compose issued 64-character hex keys and the operator console 43-character URL-safe keys.
LEGACY = re.compile(r'^[A-Za-z0-9_-]{32,128}$')
REDACT = re.compile(r'cs_(?:live|test)_[0-9a-z]{12}_[0-9A-Za-z]{43}'
                    r'|(?<![A-Za-z0-9_-])(?:[A-Za-z0-9_-]{43}|[0-9a-fA-F]{64})(?![A-Za-z0-9_-])')
PEPPER_SECRET_NAME = 'cloudsaver-identity-key-pepper'


def new_key_id():
    return ''.join(secrets.choice(CROCKFORD) for _ in range(12))


def legacy_key_id():
    """Synthetic public ID for imported keys; 'lg' keeps it distinguishable in audit."""
    return 'lg' + ''.join(secrets.choice(CROCKFORD) for _ in range(10))


def new_key(environment):
    prefix = 'cs_live_' if environment == 'production' else 'cs_test_'
    key_id = new_key_id()
    return key_id, prefix + key_id + '_' + ''.join(secrets.choice(BASE62) for _ in range(43))


def key_prefix(environment):
    return 'cs_live_' if environment == 'production' else 'cs_test_'


def parse(presented):
    """Return ('v1', key_id), ('legacy', None) or ('malformed', None) without raising."""
    if not isinstance(presented, str) or len(presented) > 128:
        return 'malformed', None
    match = V1.fullmatch(presented)
    if match:
        return 'v1', match[2]
    if presented.startswith('cs_'):
        return 'malformed', None
    if LEGACY.fullmatch(presented):
        return 'legacy', None
    return 'malformed', None


def sha256_hex(presented):
    return hashlib.sha256(presented.encode()).hexdigest()


def redact(text):
    return REDACT.sub('[redacted]', text) if isinstance(text, str) else text


class Peppers:
    """Current and previous pepper versions; the material never leaves this object."""

    def __init__(self, current_version, current, previous=None):
        if not isinstance(current, bytes) or len(current) < 32:
            raise ValueError('The key pepper must be at least 32 bytes')
        self.current_version = int(current_version)
        self._values = {self.current_version: current}
        for version, value in (previous or {}).items():
            if len(value) < 32:
                raise ValueError('Previous key peppers must be at least 32 bytes')
            self._values.setdefault(int(version), value)
        self._dummy = secrets.token_bytes(32)

    def versions(self):
        return sorted(self._values, reverse=True)

    def digest(self, presented, version=None):
        value = self._values.get(self.current_version if version is None else int(version))
        if value is None:
            return None
        return hmac.new(value, presented.encode(), hashlib.sha256).digest()

    def fingerprint(self, legacy_sha256, version=None):
        """Peppered, stable import identity that survives the upgrade to HMAC."""
        return self.digest('import:' + legacy_sha256, version)

    def dummy_compare(self, presented):
        hmac.compare_digest(hmac.new(self._dummy, presented.encode(), hashlib.sha256).digest(), self._dummy)

    @classmethod
    def from_env(cls):
        from identity.config import env
        raw = (env('KEY_PEPPER') or '').strip()
        version = int(env('KEY_PEPPER_VERSION', '1'))
        vault = env('KEYVAULT_URL')
        if not raw and vault:
            raw, version = _from_key_vault(vault)
        if not raw:
            raise RuntimeError('Set PLATFORM_KEY_PEPPER (run scripts/setup_platform.py) or configure Key Vault')
        previous = {}
        for item in filter(None, (p.strip() for p in (env('KEY_PEPPER_PREVIOUS') or '').split(','))):
            number, _, value = item.partition(':')
            previous[int(number)] = _decode(value)
        return cls(version, _decode(raw), previous)


def _decode(value):
    try:
        decoded = bytes.fromhex(value)
    except ValueError:
        raise RuntimeError('Key peppers must be hex encoded') from None
    if len(decoded) < 32:
        raise RuntimeError('Key peppers must be at least 32 bytes')
    return decoded


def _from_key_vault(url):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    secret = SecretClient(url, DefaultAzureCredential()).get_secret(PEPPER_SECRET_NAME)
    return secret.value.strip(), int((secret.properties.tags or {}).get('pepper_version', '1'))
