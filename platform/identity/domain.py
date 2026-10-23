"""Directory vocabulary and validation shared by the admin API, import and verify paths."""
from datetime import datetime, timezone
from uuid import UUID

ROLES = ('TenantAdmin', 'BillingAdmin', 'Viewer')
PROVIDERS = ('azure', 'aws', 'gcp', 'kubernetes')
SCOPE_KEYS = {'azure': 'subscription_ids', 'aws': 'aws_accounts', 'gcp': 'gcp_projects', 'kubernetes': 'kubernetes_clusters'}
PROVIDER_LABELS = {'azure': 'Azure', 'aws': 'AWS', 'gcp': 'Google Cloud', 'kubernetes': 'Kubernetes'}
STATUSES = ('active', 'suspended', 'deleted')
TIERS = ('STARTER', 'GROWTH', 'ENTERPRISE')
FAILURE_REASONS = ('malformed', 'unknown', 'secret_mismatch', 'revoked', 'expired', 'rotated_out',
                   'workspace_suspended', 'throttled')
MAX_ACTIVE_KEYS = 20
MAX_EXPIRY_DAYS = 365
DEFAULT_EXPIRY_DAYS = 90
EXPIRING_SOON_DAYS = 14
# Columns added by i0002; rows written before it (or by the 1.2.0 importer) get these values.
CUSTOMER_DEFAULTS = {'billing_contact_email': None, 'manage_billing_url': None, 'external_customer_refs': {},
                     'billing_state': 'none', 'billing_state_changed_at': None}
WORKSPACE_DEFAULTS = {'entitlements': None, 'entitlements_version': 1, 'suspended_by': None}


class IdentityError(Exception):
    status = 422

    def __init__(self, detail, status=None):
        super().__init__(detail)
        self.detail = detail
        if status:
            self.status = status


class NotFound(IdentityError):
    status = 404


class Conflict(IdentityError):
    status = 409


class StaleVersion(Conflict):
    def __init__(self):
        super().__init__('This item changed since you loaded it. Refresh and try again.')


class Throttled(IdentityError):
    status = 429

    def __init__(self, retry_after):
        super().__init__('Too many sign-in attempts. Try again in 15 minutes.')
        self.retry_after = max(1, int(retry_after))


class Unavailable(IdentityError):
    status = 503


def utcnow():
    return datetime.now(timezone.utc)


def uuid_text(value, message='Enter a valid ID.'):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise IdentityError(message) from None


def text(value, field, maximum, *, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise IdentityError(f'{field} must be 1–{maximum} characters.')
    return value.strip()


def empty_scopes():
    return {key: [] for key in SCOPE_KEYS.values()}


def configured_providers(workspace):
    return [p for p in PROVIDERS if workspace.get(SCOPE_KEYS[p])]


def normalize_scope_items(provider, items, max_subscriptions, plan_name):
    """The platform's copy of the scanners' scope rules, so the directory never accepts what they'd reject."""
    from identity.validation import normalize_sources
    if provider not in PROVIDERS:
        raise NotFound('Unknown cloud provider.')
    if not isinstance(items, list) or len(items) > 100:
        raise IdentityError('Add up to 100 entries per provider.')
    if provider == 'azure':
        result = [uuid_text(item, 'Azure subscription IDs must be UUIDs.') for item in items]
        if len(set(result)) != len(result):
            raise IdentityError('Remove duplicate Azure subscriptions.')
        if len(result) > max_subscriptions:
            raise IdentityError(f'The {plan_name} plan allows up to {max_subscriptions} Azure subscriptions.')
        return result
    key = SCOPE_KEYS[provider]
    try:
        return normalize_sources({key: items})[key]
    except ValueError as exc:
        raise IdentityError(str(exc).rstrip('.') + '.') from None


def normalize_identity_bindings(value):
    from identity.validation import normalize_identity
    cleaned = {k: v for k, v in (value or {}).items() if v not in (None, '')} if isinstance(value, dict) else value
    try:
        return normalize_identity(cleaned)
    except ValueError as exc:
        raise IdentityError(str(exc).rstrip('.') + '.') from None


def normalize_resource_access_bindings(value):
    from identity.resource_access import normalize_resource_access
    try:
        return normalize_resource_access(value, partial=True)
    except ValueError as exc:
        raise IdentityError(str(exc).rstrip('.') + '.') from None


def normalize_roles(value):
    if not isinstance(value, list) or not value or any(r not in ROLES for r in value):
        raise IdentityError('Select at least one role.')
    return [r for r in ROLES if r in value]


def parse_time(value, field='Date'):
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            raise IdentityError(f'{field} must be a valid date.') from None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso(value):
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
