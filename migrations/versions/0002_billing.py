"""Stripe plan state and durable tenant-scoped event deduplication.

Revision ID: 0002_billing
Revises: 0001_domain
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_billing'
down_revision = '0001_domain'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('organizations', sa.Column('plan_tier', sa.String(16), nullable=False, server_default='STARTER'))
    op.add_column('organizations', sa.Column('stripe_customer_id', sa.String(255), nullable=True))
    op.add_column('organizations', sa.Column('stripe_subscription_id', sa.String(255), nullable=True))
    op.add_column('organizations', sa.Column('stripe_subscription_status', sa.String(32), nullable=True))
    op.add_column('organizations', sa.Column('stripe_subscription_created', sa.BigInteger, nullable=False, server_default='0'))
    op.add_column('organizations', sa.Column('stripe_event_created', sa.BigInteger, nullable=False, server_default='0'))
    op.add_column('organizations', sa.Column('stripe_event_id', sa.String(255), nullable=True))
    op.add_column('organizations', sa.Column('stripe_last_invoice_id', sa.String(255), nullable=True))
    op.add_column('organizations', sa.Column('stripe_invoice_event_created', sa.BigInteger, nullable=False, server_default='0'))
    op.create_check_constraint('ck_organizations_plan_tier', 'organizations', "plan_tier IN ('STARTER', 'GROWTH', 'ENTERPRISE')")
    op.create_unique_constraint('uq_organizations_stripe_customer', 'organizations', ['stripe_customer_id'])
    op.create_table('stripe_events',
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_id', sa.String(255), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(128), nullable=False),
        sa.Column('event_created', sa.BigInteger, nullable=False),
        sa.Column('outcome', sa.String(64), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id', 'tenant_id'], ['organizations.id', 'organizations.tenant_id'],
                                name='fk_stripe_events_organization_owner', ondelete='RESTRICT'))
    op.execute('ALTER TABLE public.stripe_events ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE public.stripe_events FORCE ROW LEVEL SECURITY')
    expression = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(f'CREATE POLICY tenant_isolation ON public.stripe_events USING ({expression}) WITH CHECK ({expression})')
    op.execute('REVOKE ALL ON public.stripe_events FROM PUBLIC')
    op.execute('GRANT SELECT, INSERT ON public.stripe_events TO cloudsaver_app')


def downgrade():
    op.drop_table('stripe_events')
    op.drop_constraint('uq_organizations_stripe_customer', 'organizations', type_='unique')
    op.drop_constraint('ck_organizations_plan_tier', 'organizations', type_='check')
    for name in ('stripe_invoice_event_created', 'stripe_last_invoice_id', 'stripe_event_id',
                 'stripe_event_created', 'stripe_subscription_created', 'stripe_subscription_status',
                 'stripe_subscription_id', 'stripe_customer_id', 'plan_tier'):
        op.drop_column('organizations', name)
