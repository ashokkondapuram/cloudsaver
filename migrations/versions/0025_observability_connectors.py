"""Workspace observability connectors, fenced collection jobs and append-only snapshots."""
revision = '0025_observability_connectors'
down_revision = '0024_cloud_commitments'
branch_labels = depends_on = None

TABLES = {
    'observability_connectors': ('''CREATE TABLE observability_connectors (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,name varchar(80) NOT NULL,kind varchar(20) NOT NULL,config jsonb NOT NULL,
        enabled boolean NOT NULL DEFAULT true,version integer NOT NULL DEFAULT 1,created_by_hash char(64) NOT NULL,
        created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,UNIQUE(tenant_id,name))''', 'SELECT,INSERT,UPDATE'),
    'observability_jobs': ('''CREATE TABLE observability_jobs (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,request_key text NOT NULL,state varchar(20) NOT NULL,payload jsonb NOT NULL,
        lease_token uuid,lease_until timestamptz,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
        UNIQUE(tenant_id,request_key))''', 'SELECT,INSERT,UPDATE'),
    'observability_snapshots': ('''CREATE TABLE observability_snapshots (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,connector_id uuid NOT NULL,job_id uuid,status varchar(20) NOT NULL,
        payload jsonb NOT NULL,observed_at timestamptz NOT NULL)''', 'SELECT,INSERT'),
}


def upgrade():
    from alembic import op
    owner = "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
    for table, (ddl, grants) in TABLES.items():
        op.execute(ddl)
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({owner}) WITH CHECK ({owner})')
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT {grants} ON {table} TO cloudsaver_app')
    op.execute('CREATE INDEX observability_jobs_queue ON observability_jobs(tenant_id,state,created_at)')
    op.execute('CREATE INDEX observability_snapshots_latest ON observability_snapshots(tenant_id,connector_id,observed_at DESC)')


def downgrade():
    from alembic import op
    for table in reversed(list(TABLES)):
        op.execute(f'DROP TABLE {table}')
