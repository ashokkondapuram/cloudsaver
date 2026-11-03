"""Add CloudSaver integration settings to directory.platform_settings."""
revision = 'i0015_cloudsaver_integration'
down_revision = 'i0014_canonical_rule_ids'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    op.execute(
        "ALTER TABLE directory.platform_settings ADD COLUMN IF NOT EXISTS cloudsaver_integration jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade():
    from alembic import op
    op.execute('ALTER TABLE directory.platform_settings DROP COLUMN IF EXISTS cloudsaver_integration')
