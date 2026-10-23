"""Platform resource access settings, access-check jobs and cache event long poll."""
revision = 'i0003_resource_access'
down_revision = 'i0002_billing'
branch_labels = None
depends_on = None

NEW_ACTIONS = (
    'resource_access_updated', 'workspace_identity_updated', 'access_check_requested', 'access_check_completed',
)


def upgrade():
    from alembic import op
    op.execute("ALTER TABLE directory.platform_settings ADD COLUMN IF NOT EXISTS resource_access jsonb "
               "NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(resource_access) = 'object')")
    op.execute('''CREATE TABLE IF NOT EXISTS directory.access_checks (
        check_id uuid PRIMARY KEY,
        tenant_id uuid REFERENCES directory.workspaces(tenant_id),
        requested_by varchar(120) NOT NULL,
        requested_at timestamptz NOT NULL DEFAULT now(),
        claimed_by varchar(40),
        claimed_at timestamptz,
        completed_at timestamptz,
        result jsonb CHECK (result IS NULL OR octet_length(result::text) <= 16000)
    )''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_access_checks_requested ON directory.access_checks(requested_at DESC)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_access_checks_tenant ON directory.access_checks(tenant_id, requested_at DESC)')
    op.execute("ALTER TABLE identity.cache_events ADD COLUMN IF NOT EXISTS payload jsonb NOT NULL DEFAULT '{}'")
    op.execute('GRANT SELECT, INSERT, UPDATE ON directory.access_checks TO identity_app')
    op.execute('GRANT SELECT, DELETE ON directory.access_checks TO identity_retention')
    op.execute('ALTER TABLE directory.access_checks ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE directory.access_checks FORCE ROW LEVEL SECURITY')
    op.execute('CREATE POLICY app_all ON directory.access_checks TO identity_app USING (true) WITH CHECK (true)')
    op.execute("CREATE POLICY retention_read ON directory.access_checks FOR SELECT TO identity_retention "
               "USING (requested_at < now() - interval '7 days')")
    op.execute("CREATE POLICY retention_delete ON directory.access_checks FOR DELETE TO identity_retention "
               "USING (requested_at < now() - interval '7 days')")
    op.execute('ALTER TABLE identity.key_events DROP CONSTRAINT IF EXISTS key_events_action_check')
    op.execute('''ALTER TABLE identity.key_events ADD CONSTRAINT key_events_action_check
        CHECK (action IN ('issued', 'rotated', 'rotated_out', 'revoked', 'revoked_all', 'expired', 'roles_changed',
        'providers_changed', 'expiry_changed', 'renamed', 'imported', 'hash_upgraded', 'customer_created',
        'customer_updated', 'workspace_created', 'workspace_updated', 'scopes_changed', 'workspace_suspended',
        'workspace_reactivated', 'workspace_deleted', 'platform_updated', 'resource_access_updated',
        'workspace_identity_updated', 'access_check_requested', 'access_check_completed'))''')


def downgrade():
    from alembic import op
    op.execute('DROP TABLE IF EXISTS directory.access_checks')
    op.execute('ALTER TABLE directory.platform_settings DROP COLUMN IF EXISTS resource_access')
