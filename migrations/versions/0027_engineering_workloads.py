"""Persistent workload declarations, owned plan targets and transactional audit intent."""
TABLES = {
    'engineering_workloads': '''CREATE TABLE engineering_workloads (
        tenant_id uuid NOT NULL,id uuid NOT NULL,name varchar(80) NOT NULL,environment varchar(40) NOT NULL,
        provider varchar(40) NOT NULL,scope_id varchar(128) NOT NULL,owner varchar(80) NOT NULL,team varchar(80) NOT NULL,
        requirements jsonb NOT NULL,schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
        version integer NOT NULL DEFAULT 1 CHECK(version>=1),created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id))''',
    'engineering_members': '''CREATE TABLE engineering_members (
        tenant_id uuid NOT NULL,id uuid NOT NULL,workload_id uuid NOT NULL,scan_id uuid NOT NULL,
        resource_key char(64) NOT NULL,resource_id text NOT NULL,resource_type text NOT NULL,resource_name text NOT NULL,
        evidence_digest char(64) NOT NULL,created_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,id),
        UNIQUE(tenant_id,workload_id,resource_key),UNIQUE(tenant_id,workload_id,id),
        FOREIGN KEY(tenant_id,workload_id) REFERENCES engineering_workloads(tenant_id,id),
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id))''',
    'engineering_plan_links': '''CREATE TABLE engineering_plan_links (
        tenant_id uuid NOT NULL,plan_id uuid NOT NULL,workload_id uuid NOT NULL,created_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,plan_id),
        FOREIGN KEY(tenant_id,workload_id) REFERENCES engineering_workloads(tenant_id,id),
        FOREIGN KEY(tenant_id,plan_id) REFERENCES cp_plans(tenant_id,id))''',
    'engineering_plan_targets': '''CREATE TABLE engineering_plan_targets (
        tenant_id uuid NOT NULL,version_id uuid NOT NULL,workload_id uuid NOT NULL,member_id uuid NOT NULL,scan_id uuid NOT NULL,
        PRIMARY KEY(tenant_id,version_id,member_id),
        FOREIGN KEY(tenant_id,version_id) REFERENCES cp_plan_versions(tenant_id,id),
        FOREIGN KEY(tenant_id,workload_id,member_id) REFERENCES engineering_members(tenant_id,workload_id,id),
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id))''',
    'engineering_commands': '''CREATE TABLE engineering_commands (
        tenant_id uuid NOT NULL,actor_hash char(64) NOT NULL,operation_id text NOT NULL,request_key uuid NOT NULL,
        fingerprint char(64) NOT NULL,workload_id uuid NOT NULL,response jsonb NOT NULL,created_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,actor_hash,operation_id,request_key),
        FOREIGN KEY(tenant_id,workload_id) REFERENCES engineering_workloads(tenant_id,id))''',
    'engineering_events': '''CREATE TABLE engineering_events (
        tenant_id uuid NOT NULL,id uuid NOT NULL,workload_id uuid NOT NULL,version_id uuid,
        kind varchar(60) NOT NULL,actor_hash char(64) NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id),
        FOREIGN KEY(tenant_id,workload_id) REFERENCES engineering_workloads(tenant_id,id),
        FOREIGN KEY(tenant_id,version_id) REFERENCES cp_plan_versions(tenant_id,id))''',
    'engineering_outbox': '''CREATE TABLE engineering_outbox (
        tenant_id uuid NOT NULL,event_id uuid NOT NULL,state varchar(20) NOT NULL DEFAULT 'pending',
        created_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,event_id),
        CHECK(state IN ('pending','published')),
        FOREIGN KEY(tenant_id,event_id) REFERENCES engineering_events(tenant_id,id))''',
}
INDEXES = (
    'CREATE INDEX engineering_workload_scope ON engineering_workloads(tenant_id,provider,scope_id,id)',
    'CREATE INDEX engineering_members_resource ON engineering_members(tenant_id,resource_key)',
    'CREATE INDEX engineering_workload_plans ON engineering_plan_links(tenant_id,workload_id,plan_id)',
    'CREATE INDEX engineering_events_workload ON engineering_events(tenant_id,workload_id,created_at,id)',
    "CREATE INDEX engineering_outbox_pending ON engineering_outbox(tenant_id,created_at) WHERE state='pending'",
)

revision = '0027_engineering_workloads'
down_revision = '0026_control_plane'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    owner = "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
    for table, ddl in TABLES.items():
        op.execute(ddl)
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({owner}) WITH CHECK ({owner})')
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT SELECT,INSERT ON {table} TO cloudsaver_app')
    op.execute('GRANT UPDATE(name,environment,owner,team,requirements,version,updated_at) ON engineering_workloads TO cloudsaver_app')
    for ddl in INDEXES:
        op.execute(ddl)


def downgrade():
    from alembic import op
    from sqlalchemy import text
    db = op.get_bind()
    op.execute('LOCK TABLE ' + ','.join(TABLES) + ' IN ACCESS EXCLUSIVE MODE')
    for table in TABLES:
        op.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')
    try:
        populated = any(db.execute(text(f'SELECT EXISTS(SELECT 1 FROM {table})')).scalar() for table in TABLES)
    finally:
        for table in TABLES:
            op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
    if populated:
        raise RuntimeError('Engineering history requires a reviewed data-preserving rollback')
    for table in reversed(TABLES):
        op.execute(f'DROP TABLE {table}')
