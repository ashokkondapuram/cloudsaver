"""Atomic, idempotent import of version-1 CloudSaver billing exports.

Legacy exports contain no service period or agreed amount. Supply explicit terms per workspace;
never invent a paid period from a provider event timestamp. No Stripe requests are made.
"""
from datetime import datetime, timezone
from decimal import Decimal
import re
from uuid import uuid4

from identity.billing.domain import currency, timestamp, whole, billing_state
from identity.billing.providers import identifier
from identity.domain import Conflict, IdentityError, uuid_text

PRECISION = {'USD': 2, 'CAD': 2, 'EUR': 2, 'GBP': 2, 'INR': 2, 'AUD': 2, 'JPY': 0, 'KWD': 3}
ACTOR = {'actor': 'billing-import', 'actor_type': 'system'}


def amount_minor(value, code):
    currency(code)
    if code not in PRECISION or not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value):
        raise IdentityError('Use an exact nonnegative decimal amount string and a supported currency.')
    scale = PRECISION[code]
    if '.' in value and len(value.split('.')[1]) > scale:
        raise IdentityError('Amount exceeds the currency minor-unit precision.')
    return whole(int(Decimal(value) * (10 ** scale)), 'Amount', 0)


def import_billing(service, document, *, terms=None):
    def reject_floats(value):
        if isinstance(value, float):
            raise IdentityError('Floating-point billing values are not accepted.')
        if isinstance(value, dict):
            for item in value.values():
                reject_floats(item)
        elif isinstance(value, list):
            for item in value:
                reject_floats(item)
    reject_floats(document)
    reject_floats(terms)
    if not isinstance(document, dict) or type(document.get('version')) is not int or document['version'] != 1:
        raise IdentityError('Unsupported billing export version.')
    organizations, events = document.get('organizations'), document.get('stripe_events')
    if not isinstance(organizations, list) or not isinstance(events, list) or len(organizations) > 10000 or len(events) > 100000:
        raise IdentityError('Invalid or oversized billing export.')
    terms = terms or {}
    if not isinstance(terms, dict):
        raise IdentityError('Billing terms must be an object keyed by workspace UUID.')
    seen, prepared = set(), []
    for row in organizations:
        if not isinstance(row, dict):
            raise IdentityError('Invalid organization entry.')
        tenant_id = uuid_text(row.get('tenant_id'))
        if tenant_id in seen:
            raise IdentityError('Duplicate workspace in billing export.')
        seen.add(tenant_id)
        customer_ref = identifier(row['stripe_customer_id'], 'cus_') if row.get('stripe_customer_id') else None
        subscription_ref = identifier(row['stripe_subscription_id'], 'sub_') if row.get('stripe_subscription_id') else None
        if subscription_ref and not customer_ref:
            raise IdentityError('A provider subscription requires an explicit customer reference.')
        agreement = terms.get(tenant_id)
        if subscription_ref and not agreement:
            raise IdentityError('Legacy exports omit billing terms. Supply explicit amount, currency, and service dates.')
        if agreement:
            if not isinstance(agreement, dict):
                raise IdentityError('Invalid subscription terms.')
            start, end = timestamp(agreement.get('current_period_start'), 'Period start'), timestamp(agreement.get('current_period_end'), 'Period end')
            if end <= start or agreement.get('interval') not in ('month', 'year', 'custom'):
                raise IdentityError('Choose valid service dates and interval.')
            agreement = dict(agreement, current_period_start=start, current_period_end=end,
                amount_minor=amount_minor(agreement.get('amount'), agreement.get('currency')),
                grace_days=whole(agreement.get('grace_days', 14), 'Grace days', 0, 60))
        if row.get('subscription_status') not in (None, 'active', 'trialing', 'past_due', 'canceled', 'expired'):
            raise IdentityError('Unsupported legacy subscription status.')
        prepared.append((tenant_id, customer_ref, subscription_ref, row, agreement))
    normalized_events = []
    for event in events:
        if not isinstance(event, dict) or uuid_text(event.get('tenant_id')) not in seen:
            raise IdentityError('Provider event references an unlisted workspace.')
        event_id = identifier(event.get('event_id'), 'evt_')
        kind = event.get('event_type')
        if not isinstance(kind, str) or not 1 <= len(kind) <= 80:
            raise IdentityError('Invalid provider event type.')
        created = timestamp(event.get('created_at'), 'Provider event time')
        normalized_events.append((event['tenant_id'], event_id, kind, int(created.timestamp())))
    now, changed, customers = service.now(), 0, set()
    with service.store.transaction() as tx:
        mapping = {}
        for tenant_id, customer_ref, subscription_ref, row, agreement in prepared:
            workspace = tx.get_workspace(tenant_id)
            if not workspace or workspace['status'] == 'deleted':
                raise IdentityError('Export references an unavailable workspace.')
            customer_id = workspace['customer_id']
            mapping[tenant_id] = customer_id
            customer = tx.get_customer(customer_id, lock=True)
            if not customer or customer['status'] == 'deleted':
                raise IdentityError('Workspace has no available customer.')
            if not tx.get_plan(row.get('plan_tier')):
                raise IdentityError('Export references an unknown plan.')
            refs = dict(customer.get('external_customer_refs') or {})
            if customer_ref:
                owner = tx.customer_by_external_ref('stripe', customer_ref)
                if (owner and owner['id'] != customer_id) or (refs.get('stripe') and refs['stripe'] != customer_ref):
                    raise Conflict('Stripe customer reference ownership conflicts with existing data.')
                if refs.get('stripe') != customer_ref:
                    tx.update_customer(customer_id, customer['version'], dict(external_customer_refs={**refs, 'stripe': customer_ref},
                        updated_at=now, updated_by=ACTOR['actor']))
                    changed += 1
            if subscription_ref:
                current = tx.latest_provider_subscription(customer_id, 'stripe') or tx.current_subscription(customer_id)
                if current:
                    expected = dict(plan_code=row['plan_tier'], amount_minor=agreement['amount_minor'], currency=agreement['currency'],
                        current_period_start=agreement['current_period_start'], current_period_end=agreement['current_period_end'],
                        interval=agreement['interval'], grace_days=agreement['grace_days'],
                        status=row.get('subscription_status') or 'expired', provider='stripe')
                    if current.get('external_subscription_ref') != subscription_ref or any(current.get(k) != v for k, v in expected.items()):
                        raise Conflict('Existing commercial subscription conflicts with imported terms.')
                else:
                    tx.insert_subscription(dict(id=str(uuid4()), customer_id=customer_id, plan_code=row['plan_tier'],
                        status=row.get('subscription_status') or 'expired', provider='stripe', external_subscription_ref=subscription_ref,
                        current_period_start=agreement['current_period_start'], current_period_end=agreement['current_period_end'],
                        cancel_at_period_end=False, canceled_at=None, amount_minor=agreement['amount_minor'], currency=agreement['currency'],
                        interval=agreement['interval'], grace_days=agreement['grace_days'], entitlement_overrides=None,
                        notes='Imported from legacy billing with explicit operator terms.', created_at=now, updated_at=now,
                        created_by=ACTOR['actor'], updated_by=ACTOR['actor'], version=1))
                    changed += 1
            customers.add(customer_id)
        for tenant_id, event_id, kind, created in normalized_events:
            prior = tx.provider_event('stripe', event_id)
            if prior:
                if prior.get('customer_id') != mapping[tenant_id]:
                    raise Conflict('Provider event already belongs to another customer.')
                continue
            tx.insert_provider_event(dict(provider='stripe', event_id=event_id, event_type=kind,
                event_created=created, customer_id=mapping[tenant_id], outcome='legacy_import'))
            changed += 1
        if changed:
            for customer_id in customers:
                service._refresh_customer_billing(tx, customer_id, now)
                service._sync_customer_entitlements(tx, customer_id, ACTOR, now)
            service._event(tx, ACTOR, 'billing_imported', details={'workspaces': len(mapping), 'changes': changed})
            service._publish([{'directory': True, 'event': 'directory_changed'}], tx)
    return {'changed': changed, 'workspaces': len(prepared)}


def main():
    import argparse
    import json
    from pathlib import Path
    from identity.app import build_service
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--terms', required=True, help='Explicit commercial terms keyed by workspace UUID')
    args = parser.parse_args()

    def invalid(value):
        raise IdentityError('Non-finite or floating-point JSON amounts are not accepted.')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IdentityError('Duplicate JSON object key.')
            result[key] = value
        return result

    def read(path):
        raw = Path(path).read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise IdentityError('Import file exceeds 16 MiB.')
        return json.loads(raw, parse_float=invalid, parse_constant=invalid, object_pairs_hook=unique)

    print(json.dumps(import_billing(build_service(), read(args.input), terms=read(args.terms))))


if __name__ == '__main__':
    main()
