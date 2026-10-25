"""Durable billing jobs with tenant isolation and single-use scope leases."""
revision='0021_billing_jobs'
down_revision='0020_billing_and_agent_gitops'
branch_labels=depends_on=None

def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE billing_sync_jobs (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,request_key text NOT NULL,state varchar(32) NOT NULL,
        payload jsonb NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
        lease_token uuid,lease_until timestamptz,UNIQUE(tenant_id,request_key))''')
    op.execute('CREATE INDEX billing_jobs_queue ON billing_sync_jobs(tenant_id,state,created_at)')
    op.execute('ALTER TABLE billing_sync_jobs ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE billing_sync_jobs FORCE ROW LEVEL SECURITY')
    owner="tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
    op.execute(f'CREATE POLICY tenant_isolation ON billing_sync_jobs USING ({owner}) WITH CHECK ({owner})')
    op.execute('REVOKE ALL ON billing_sync_jobs FROM PUBLIC')
    op.execute('GRANT SELECT,INSERT,UPDATE ON billing_sync_jobs TO cloudsaver_app')

def downgrade():
    from alembic import op
    op.execute('DROP TABLE billing_sync_jobs')
