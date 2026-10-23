import json
import stat

import scripts.export_billing as export_billing

TID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


class Result(list):
    def fetchall(self):
        return list(self)


class FakeDb:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if 'FROM public.tenant_registry' in sql:
            return Result([(TID,)])
        if 'DISTINCT tenant_id FROM public.organizations' in sql:
            return Result([(OTHER,)])
        if 'FROM public.organizations WHERE' in sql:
            if params[0] == TID:
                return Result([(TID, 'GROWTH', 'cus_placeholder', 'sub_placeholder', 'active', 1767322800, 1767322900,
                                'evt_placeholder', None, None)])
            return Result([(OTHER, 'STARTER', None, None, None, None, None, None, None, None)])
        if 'FROM public.stripe_events' in sql:
            return Result([('evt_placeholder', 'invoice.paid', 1767322900)] if params[0] == TID else [])
        return Result()


def test_export_is_read_only_and_covers_every_tenant(tmp_path, capsys):
    db = FakeDb()
    output = tmp_path / 'billing-export.json'
    export_billing.main(['--output', str(output)], connect=lambda: db)
    assert db.statements[0][0] == 'SET TRANSACTION READ ONLY'
    assert not any(word in sql.upper() for sql, _ in db.statements for word in ('INSERT', 'UPDATE ', 'DELETE'))
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    document = json.loads(output.read_text())
    assert document['version'] == 1 and document['exported_at'].endswith('Z')
    growth, starter = document['organizations']
    assert growth == {'tenant_id': TID, 'plan_tier': 'GROWTH', 'stripe_customer_id': 'cus_placeholder',
                      'stripe_subscription_id': 'sub_placeholder', 'subscription_status': 'active',
                      'current_period_end': None, 'billing_watermark': {
                          'stripe_subscription_created': 1767322800, 'stripe_event_created': 1767322900,
                          'stripe_event_id': 'evt_placeholder', 'stripe_last_invoice_id': None,
                          'stripe_invoice_event_created': None}}
    assert starter['tenant_id'] == OTHER and starter['billing_watermark'] is None
    assert document['stripe_events'] == [{'event_id': 'evt_placeholder', 'event_type': 'invoice.paid',
                                          'created_at': '2026-01-02T03:01:40Z'}]
    assert 'Exported 2 organizations and 1 Stripe events.' in capsys.readouterr().err


def test_export_requires_a_database_url(monkeypatch):
    import pytest
    monkeypatch.delenv('CLOUDSAVER_MIGRATION_URL', raising=False)
    monkeypatch.delenv('CLOUDSAVER_DATABASE_URL', raising=False)
    with pytest.raises(SystemExit):
        export_billing.database_url()
    monkeypatch.setenv('CLOUDSAVER_DATABASE_URL', 'postgresql+psycopg://user@db/cloudsaver')
    assert export_billing.database_url() == 'postgresql://user@db/cloudsaver'
