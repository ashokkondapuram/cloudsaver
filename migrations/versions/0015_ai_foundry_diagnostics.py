"""Tenant-isolated, append-only diagnostic records; does not remove legacy billing data."""
revision = '0015_ai_foundry_diagnostics'
down_revision = '0013_billing_projection'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE ai_connection_diagnostics (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,provider varchar(8) NOT NULL CHECK(provider IN ('azure','aws','gcp')),
        target_id varchar(40) NOT NULL,actor char(64) NOT NULL,result jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(), CHECK(octet_length(result::text)<=8000))''')
    op.execute('CREATE INDEX ix_ai_diagnostics_history ON ai_connection_diagnostics(tenant_id,created_at DESC,id DESC)')
    op.execute('ALTER TABLE ai_connection_diagnostics ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE ai_connection_diagnostics FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON ai_connection_diagnostics USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)")
    op.execute('REVOKE ALL ON ai_connection_diagnostics FROM PUBLIC')
    op.execute('GRANT SELECT,INSERT ON ai_connection_diagnostics TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.execute('DROP TABLE ai_connection_diagnostics')
