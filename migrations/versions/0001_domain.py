"""Normalized tenant domain with database-enforced ownership boundaries.

Revision ID: 0001_domain
Revises: None
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_domain'
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
OWNER = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade():
    op.create_table('organizations',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('tenant_id', UUID, nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('id', 'tenant_id', name='uq_organizations_id_tenant'))
    op.create_index('ix_organizations_tenant', 'organizations', ['tenant_id'])
    op.create_table('tenants',
        sa.Column('tenant_id', UUID, primary_key=True),
        sa.Column('organization_id', UUID, nullable=False),
        sa.Column('display_name', sa.String(120), nullable=False),
        sa.Column('connection_status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id', 'tenant_id'], ['organizations.id', 'organizations.tenant_id'],
                                name='fk_tenants_organization_owner', ondelete='RESTRICT'))
    op.create_index('ix_tenants_organization', 'tenants', ['organization_id', 'tenant_id'])
    op.create_table('subscriptions',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('tenant_id', UUID, nullable=False),
        sa.Column('subscription_id', UUID, nullable=False),
        sa.Column('display_name', sa.String(120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], name='fk_subscriptions_tenant', ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id', 'subscription_id', name='uq_subscriptions_tenant_subscription'))
    op.create_table('waste_findings',
        sa.Column('id', UUID, primary_key=True),
        sa.Column('tenant_id', UUID, nullable=False),
        sa.Column('subscription_id', UUID, nullable=False),
        sa.Column('resource_id', sa.Text, nullable=False),
        sa.Column('resource_name', sa.String(256), nullable=False),
        sa.Column('resource_type', sa.String(256), nullable=False),
        sa.Column('resource_group', sa.String(256), nullable=False),
        sa.Column('rule_id', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('details', sa.Text, nullable=False),
        sa.Column('evidence', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('estimated_monthly_waste_usd', sa.Numeric(18, 2), nullable=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id', 'subscription_id'], ['subscriptions.tenant_id', 'subscriptions.subscription_id'],
                                name='fk_waste_findings_subscription_owner', ondelete='RESTRICT'),
        sa.CheckConstraint("severity IN ('HIGH', 'MEDIUM', 'LOW', 'INFO')", name='ck_waste_findings_severity'),
        sa.CheckConstraint('estimated_monthly_waste_usd IS NULL OR estimated_monthly_waste_usd >= 0', name='ck_waste_findings_nonnegative_cost'))
    op.create_index('ix_waste_findings_owner_observed', 'waste_findings', ['tenant_id', 'observed_at'])
    for table in ('organizations', 'tenants', 'subscriptions', 'waste_findings'):
        op.execute(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tenant_isolation ON public.{table} USING ({OWNER}) WITH CHECK ({OWNER})')
        op.execute(f'REVOKE ALL ON public.{table} FROM PUBLIC')
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON public.{table} TO cloudsaver_app')
    op.execute('GRANT USAGE ON SCHEMA public TO cloudsaver_app')


def downgrade():
    for table in ('waste_findings', 'subscriptions', 'tenants', 'organizations'):
        op.drop_table(table)
