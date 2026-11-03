"""Per-workspace dashboard UI theme presets on directory.platform_settings."""
revision = 'i0016_workspace_ui_themes'
down_revision = 'i0015_cloudsaver_integration'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    op.execute(
        "ALTER TABLE directory.platform_settings ADD COLUMN IF NOT EXISTS workspace_ui_themes jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade():
    from alembic import op
    op.execute('ALTER TABLE directory.platform_settings DROP COLUMN IF EXISTS workspace_ui_themes')
