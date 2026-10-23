"""Plan change requests from CloudSaver billing admins (approval queue; Stripe-ready)."""
revision = 'i0004_plan_change_requests'
down_revision = 'i0003_resource_access'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE billing.plan_change_requests (
        id uuid PRIMARY KEY,
        customer_id uuid NOT NULL REFERENCES directory.customers(id),
        tenant_id uuid NOT NULL REFERENCES directory.workspaces(tenant_id),
        current_plan_code varchar(16) NOT NULL,
        requested_plan_code varchar(16) NOT NULL,
        status varchar(24) NOT NULL CHECK (status IN (
            'pending_approval','pending_payment','approved','rejected','canceled')),
        payment_provider varchar(16) NOT NULL DEFAULT 'manual'
            CHECK (payment_provider IN ('manual','stripe')),
        stripe_checkout_session_id varchar(255),
        requested_by varchar(120) NOT NULL,
        reviewed_by varchar(120),
        review_note varchar(500),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 1)''')
    op.execute('CREATE INDEX ix_plan_change_requests_status ON billing.plan_change_requests(status, created_at DESC)')
    op.execute('CREATE INDEX ix_plan_change_requests_tenant ON billing.plan_change_requests(tenant_id)')
    op.execute('GRANT SELECT, INSERT, UPDATE ON billing.plan_change_requests TO identity_app')
    op.execute('ALTER TABLE billing.plan_change_requests ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE billing.plan_change_requests FORCE ROW LEVEL SECURITY')
    op.execute('CREATE POLICY app_all ON billing.plan_change_requests TO identity_app USING (true) WITH CHECK (true)')


def downgrade():
    from alembic import op
    op.execute('DROP TABLE IF EXISTS billing.plan_change_requests')
