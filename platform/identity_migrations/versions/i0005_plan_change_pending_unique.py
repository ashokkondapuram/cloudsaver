"""One pending plan-change request per workspace (approval or payment)."""
revision = 'i0005_plan_change_pending_unique'
down_revision = 'i0004_plan_change_requests'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE UNIQUE INDEX ux_plan_change_requests_pending_tenant
        ON billing.plan_change_requests (tenant_id)
        WHERE status IN ('pending_approval', 'pending_payment')''')


def downgrade():
    from alembic import op
    op.execute('DROP INDEX IF EXISTS billing.ux_plan_change_requests_pending_tenant')
