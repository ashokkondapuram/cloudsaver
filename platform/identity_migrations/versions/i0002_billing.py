"""Billing schema, directory billing columns and cache event long poll."""
revision = 'i0002_billing'
down_revision = 'i0001_directory_identity'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('CREATE SCHEMA IF NOT EXISTS billing')
    op.execute('REVOKE ALL ON SCHEMA billing FROM PUBLIC')
    op.execute('GRANT USAGE ON SCHEMA billing TO identity_app, identity_retention')
    audit = ('created_at timestamptz NOT NULL DEFAULT now(), created_by varchar(120) NOT NULL, '
             'updated_at timestamptz NOT NULL DEFAULT now(), updated_by varchar(120) NOT NULL, version integer NOT NULL DEFAULT 1')
    op.execute(f'''CREATE TABLE billing.plans (
        code varchar(16) PRIMARY KEY, name varchar(80) NOT NULL, description varchar(500),
        status varchar(16) NOT NULL CHECK (status IN ('active','retired')),
        list_price_minor bigint, currency char(3), interval varchar(16) CHECK (interval IS NULL OR interval IN ('month','year','custom')),
        external_price_refs jsonb NOT NULL DEFAULT '{{}}', entitlements jsonb NOT NULL, {audit})''')
    op.execute(f'''CREATE TABLE billing.settings (
        id smallint PRIMARY KEY CHECK (id = 1),
        default_plan_code varchar(16) NOT NULL REFERENCES billing.plans(code),
        default_grace_days smallint NOT NULL CHECK (default_grace_days BETWEEN 0 AND 60),
        lapsed_action varchar(16) NOT NULL CHECK (lapsed_action IN ('downgrade','suspend')),
        lapsed_plan_code varchar(16) NOT NULL REFERENCES billing.plans(code),
        default_manage_billing_url varchar(2048),
        require_subscription_for_keys boolean NOT NULL, {audit})''')
    op.execute(f'''CREATE TABLE billing.subscriptions (
        id uuid PRIMARY KEY, customer_id uuid NOT NULL REFERENCES directory.customers(id),
        plan_code varchar(16) NOT NULL REFERENCES billing.plans(code),
        status varchar(16) NOT NULL CHECK (status IN ('trialing','active','past_due','canceled','expired')),
        provider varchar(16) NOT NULL CHECK (provider IN ('manual','stripe')),
        external_subscription_ref varchar(255),
        current_period_start timestamptz NOT NULL, current_period_end timestamptz NOT NULL,
        cancel_at_period_end boolean NOT NULL DEFAULT false, canceled_at timestamptz,
        amount_minor bigint NOT NULL, currency char(3) NOT NULL, interval varchar(16) NOT NULL,
        grace_days smallint NOT NULL, entitlement_overrides jsonb, notes varchar(500), {audit})''')
    op.execute('CREATE UNIQUE INDEX ux_subscriptions_current ON billing.subscriptions(customer_id) '
               "WHERE status NOT IN ('canceled','expired')")
    op.execute(f'''CREATE TABLE billing.payments (
        id uuid PRIMARY KEY, customer_id uuid NOT NULL REFERENCES directory.customers(id),
        subscription_id uuid REFERENCES billing.subscriptions(id),
        amount_minor bigint NOT NULL CHECK (amount_minor > 0), currency char(3) NOT NULL,
        status varchar(16) NOT NULL CHECK (status IN ('pending','paid','failed','refunded','void')),
        method varchar(16) NOT NULL CHECK (method IN ('bank_transfer','card','check','other')),
        reference varchar(80) NOT NULL, invoice_date date, due_date date, paid_at timestamptz,
        period_start date NOT NULL, period_end date NOT NULL CHECK (period_end >= period_start),
        provider varchar(16) NOT NULL CHECK (provider IN ('manual','stripe')),
        external_payment_ref varchar(255) UNIQUE, notes varchar(500),
        void_reason varchar(200), voided_by varchar(120), voided_at timestamptz, {audit})''')
    op.execute('''CREATE TABLE billing.provider_events (
        provider varchar(16) NOT NULL, event_id varchar(255) NOT NULL, event_type varchar(120) NOT NULL,
        event_created bigint, customer_id uuid, outcome varchar(64) NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (provider, event_id))''')
    for table in ('billing.plans', 'billing.settings', 'billing.subscriptions', 'billing.payments'):
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON {table} TO identity_app')
    op.execute('GRANT SELECT, INSERT ON billing.provider_events TO identity_app')
    op.execute('GRANT SELECT, DELETE ON billing.provider_events TO identity_retention')
    for code, name, max_subscriptions in (('STARTER', 'Starter', 2), ('GROWTH', 'Growth', 10), ('ENTERPRISE', 'Enterprise', 1000)):
        op.execute(
            f"INSERT INTO billing.plans (code, name, description, status, entitlements, created_by, updated_by) "
            f"VALUES ('{code}', '{name}', '{name} plan', 'active', "
            f"jsonb_build_object('max_subscriptions', {max_subscriptions}), 'bootstrap', 'bootstrap') ON CONFLICT DO NOTHING"
        )
    op.execute("INSERT INTO billing.settings (id, default_plan_code, default_grace_days, lapsed_action, lapsed_plan_code, "
               "require_subscription_for_keys, created_by, updated_by) VALUES "
               "(1,'STARTER',14,'downgrade','STARTER',true,'bootstrap','bootstrap') ON CONFLICT DO NOTHING")
    for table in ('billing.plans', 'billing.settings', 'billing.subscriptions', 'billing.payments', 'billing.provider_events'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY app_all ON {table} TO identity_app USING (true) WITH CHECK (true)')
    op.execute("ALTER TABLE directory.customers ADD COLUMN IF NOT EXISTS billing_contact_email varchar(254)")
    op.execute("ALTER TABLE directory.customers ADD COLUMN IF NOT EXISTS manage_billing_url varchar(2048)")
    op.execute("ALTER TABLE directory.customers ADD COLUMN IF NOT EXISTS external_customer_refs jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE directory.customers ADD COLUMN IF NOT EXISTS billing_state varchar(16) NOT NULL DEFAULT 'none'")
    op.execute("ALTER TABLE directory.customers ADD COLUMN IF NOT EXISTS billing_state_changed_at timestamptz")
    op.execute("ALTER TABLE directory.workspaces ADD COLUMN IF NOT EXISTS entitlements jsonb")
    op.execute("ALTER TABLE directory.workspaces ADD COLUMN IF NOT EXISTS entitlements_version integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE directory.workspaces ADD COLUMN IF NOT EXISTS suspended_by varchar(120)")
    op.execute('''CREATE TABLE IF NOT EXISTS identity.cache_events (
        seq bigserial PRIMARY KEY, tenant_id uuid, key_id varchar(12), event varchar(64) NOT NULL,
        directory boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now())''')
    op.execute('GRANT SELECT, INSERT ON identity.cache_events TO identity_app')
    op.execute('GRANT SELECT, DELETE ON identity.cache_events TO identity_retention')
    op.execute('ALTER TABLE identity.cache_events ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE identity.cache_events FORCE ROW LEVEL SECURITY')
    op.execute('CREATE POLICY app_all ON identity.cache_events TO identity_app USING (true) WITH CHECK (true)')
    op.execute("CREATE POLICY retention_read ON identity.cache_events FOR SELECT TO identity_retention "
               "USING (created_at < now() - interval '1 day')")
    op.execute("CREATE POLICY retention_delete ON identity.cache_events FOR DELETE TO identity_retention "
               "USING (created_at < now() - interval '1 day')")

def downgrade():
    from alembic import op
    op.execute('DROP SCHEMA billing CASCADE')
    op.execute('DROP TABLE IF EXISTS identity.cache_events')
