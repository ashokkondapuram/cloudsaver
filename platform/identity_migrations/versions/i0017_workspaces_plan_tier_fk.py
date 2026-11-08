"""Replace the hard-coded workspaces.plan_tier CHECK with a foreign key to billing.plans(code).

Operators can create custom plan codes (domain.py PLAN_CODE: ^[A-Z][A-Z0-9_]{1,15}$), but the
original CHECK only allowed STARTER/GROWTH/ENTERPRISE, so subscribing a workspace to any other
plan raised a CheckViolation. billing.plans(code) is the real source of truth for valid plans.
"""
revision = 'i0017_workspaces_plan_tier_fk'
down_revision = 'i0016_workspace_ui_themes'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    op.execute('ALTER TABLE directory.workspaces DROP CONSTRAINT IF EXISTS workspaces_plan_tier_check')
    op.execute('ALTER TABLE directory.workspaces ADD CONSTRAINT workspaces_plan_tier_fkey '
               'FOREIGN KEY (plan_tier) REFERENCES billing.plans(code)')


def downgrade():
    from alembic import op
    op.execute('ALTER TABLE directory.workspaces DROP CONSTRAINT IF EXISTS workspaces_plan_tier_fkey')
    op.execute("ALTER TABLE directory.workspaces ADD CONSTRAINT workspaces_plan_tier_check "
               "CHECK (plan_tier IN ('STARTER','GROWTH','ENTERPRISE'))")
