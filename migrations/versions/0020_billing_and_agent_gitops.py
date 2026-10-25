"""Durable automatic billing and agent-to-IaC review linkage."""
revision = '0020_billing_and_agent_gitops'
down_revision = '0019_multicloud_governance_and_pillars'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    for table in ('billing_sync_runs', 'agent_gitops_syncs'):
        op.execute(f'''CREATE TABLE {table} (
            id uuid PRIMARY KEY,tenant_id uuid NOT NULL,binding_key text NOT NULL,
            state varchar(40) NOT NULL,payload jsonb NOT NULL,
            created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,lease_until timestamptz NOT NULL)''')
        op.execute(f'CREATE INDEX {table}_owner ON {table}(tenant_id,created_at DESC)')
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        owner = "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
        op.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({owner}) WITH CHECK ({owner})')
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT SELECT,INSERT,UPDATE ON {table} TO cloudsaver_app')


def downgrade():
    from alembic import op
    for table in ('agent_gitops_syncs', 'billing_sync_runs'):
        op.execute(f'DROP TABLE {table}')
