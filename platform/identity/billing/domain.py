"""Billing vocabulary, input validation and the billing-state rules."""
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from identity.domain import IdentityError, parse_time, text

PLAN_STATUSES = ('active', 'retired')
INTERVALS = ('month', 'year', 'custom')
SUBSCRIPTION_STATUSES = ('trialing', 'active', 'past_due', 'canceled', 'expired')
ENDED = ('canceled', 'expired')
PAYMENT_STATUSES = ('pending', 'paid', 'failed', 'refunded', 'void')
PAYMENT_METHODS = ('bank_transfer', 'card', 'check', 'other')
PAYMENT_TRANSITIONS = {'pending': ('paid', 'failed'), 'paid': ('refunded',), 'failed': (), 'refunded': (), 'void': ()}
BILLING_STATES = ('active', 'grace', 'lapsed', 'none')
LAPSED_ACTIONS = ('downgrade', 'suspend')
PROVIDER_NAMES = ('manual', 'stripe')

CARD_NUMBER = 'Remove the card number. Use the invoice or remittance reference instead.'
ISSUANCE_BLOCKED = ("This customer doesn't have an active billing subscription. Create one on the customer's "
                    'Billing tab and reconcile the service period before you issue keys.')
PLAN_LOCKED = ("This workspace's plan comes from the customer's subscription. Change it on the customer's "
               'Billing tab.')
STRIPE_MANAGED = 'Stripe manages this subscription. You can change only notes and entitlement overrides.'
STRIPE_OFF = "Stripe isn't configured"

PLAN_CODE = re.compile(r'^[A-Z][A-Z0-9_]{1,15}$')
CURRENCY = re.compile(r'^[A-Z]{3}$')
EMAIL = re.compile(r'^[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$')
DIGIT_RUN = re.compile(r'\d(?:[ -]?\d)*')


def luhn(digits):
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def has_card_number(value):
    """True when the text holds a 13–19 digit run (spaces or dashes allowed) that passes the Luhn check."""
    for run in DIGIT_RUN.findall(value or ''):
        digits = run.replace(' ', '').replace('-', '')
        if 13 <= len(digits) <= 19 and luhn(digits):
            return True
    return False


def free_text(value, field, maximum, *, required=False):
    if value in (None, '') and not required:
        return None
    result = text(value, field, maximum)
    if has_card_number(result):
        raise IdentityError(CARD_NUMBER)
    return result


def whole(value, field, low=0, high=10**15):
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise IdentityError(f'{field} must be a whole number from {low:,} to {high:,}.')
    return value


def currency(value):
    if not isinstance(value, str) or not CURRENCY.fullmatch(value):
        raise IdentityError('Choose a three-letter currency code, for example USD.')
    return value


def choice(value, allowed, message):
    if value not in allowed:
        raise IdentityError(message)
    return value


def boolean(value, message):
    if not isinstance(value, bool):
        raise IdentityError(message)
    return value


def https_url(value, field='Manage billing link'):
    if value in (None, ''):
        return None
    parts = urlsplit(value) if isinstance(value, str) and len(value) <= 2048 else None
    if (not parts or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment):
        raise IdentityError(f'{field} must be an https link without credentials, a query or a fragment.')
    return value


def email(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.fullmatch(value):
        raise IdentityError('Enter a valid billing email.')
    return value


def day(value, field):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise IdentityError(f'{field} must be a date (YYYY-MM-DD).') from None


def optional_day(value, field):
    return None if value in (None, '') else day(value, field)


def day_start(value):
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def timestamp(value, field):
    return parse_time(value, field)


def billing_state(subscription, now):
    """(state, grace_ends_at) for a customer's latest subscription; see the evaluator table in the spec."""
    if subscription is None:
        return 'none', None
    end = subscription['current_period_end']
    if subscription['status'] in ENDED:
        return 'lapsed', subscription['canceled_at'] or end
    if subscription['cancel_at_period_end'] and now >= end:
        return 'lapsed', end
    grace_end = end + timedelta(days=subscription['grace_days'])
    if subscription['status'] == 'past_due':
        return ('grace' if now < grace_end else 'lapsed'), grace_end
    if now < end:
        return 'active', None
    if now < grace_end and not subscription['cancel_at_period_end']:
        return 'grace', grace_end
    return 'lapsed', grace_end


def iso_day(value):
    return value.isoformat() if value else None
