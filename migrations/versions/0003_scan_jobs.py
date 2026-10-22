"""Durable tenant-scoped scan job state and explicit active subscriptions.

Revision ID: 0003_scan_jobs
Revises: 0002_billing
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003_scan_jobs'
down_revision = '0002_billing'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('subscriptions', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('scan_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='queued'),
        sa.Column('scan_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notification_status', sa.String(24), nullable=False, server_default='not_requested'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], name='fk_scan_jobs_tenant', ondelete='RESTRICT'),
        sa.CheckConstraint("status IN ('queued','running','completed','failed')", name='ck_scan_jobs_status'),
        sa.CheckConstraint("notification_status IN ('not_requested','sent','failed')", name='ck_scan_jobs_notification'),
        sa.CheckConstraint('attempts >= 0', name='ck_scan_jobs_attempts'))
    op.create_index('ix_scan_jobs_tenant_created', 'scan_jobs', ['tenant_id', 'created_at'])
    owner = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute('ALTER TABLE public.scan_jobs ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE public.scan_jobs FORCE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tenant_isolation ON public.scan_jobs USING ({owner}) WITH CHECK ({owner})')
    op.execute('REVOKE ALL ON public.scan_jobs FROM PUBLIC')
    op.execute('GRANT SELECT, INSERT, UPDATE ON public.scan_jobs TO cloudsaver_app')


def downgrade():
    op.drop_table('scan_jobs')
    op.drop_column('subscriptions', 'active')
