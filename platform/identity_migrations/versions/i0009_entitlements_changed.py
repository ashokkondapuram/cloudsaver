"""Allow entitlements_changed directory changes (plan and subscription updates)."""
revision = 'i0009_entitlements_changed'
down_revision = 'i0008_cache_events_sequence'
branch_labels = None
depends_on = None

CHECK = 'directory.directory_changes'


def upgrade():
    from alembic import op
    op.execute(f'ALTER TABLE {CHECK} DROP CONSTRAINT IF EXISTS directory_changes_change_type_check')
    op.execute(f"ALTER TABLE {CHECK} ADD CONSTRAINT directory_changes_change_type_check CHECK (change_type IN "
               "('workspace_upserted','workspace_deleted','platform_updated','entitlements_changed'))")


def downgrade():
    from alembic import op
    op.execute(f"DELETE FROM {CHECK} WHERE change_type = 'entitlements_changed'")
    op.execute(f'ALTER TABLE {CHECK} DROP CONSTRAINT IF EXISTS directory_changes_change_type_check')
    op.execute(f"ALTER TABLE {CHECK} ADD CONSTRAINT directory_changes_change_type_check CHECK (change_type IN "
               "('workspace_upserted','workspace_deleted','platform_updated'))")
