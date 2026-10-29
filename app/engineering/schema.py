"""Additive pilot schema. Existing control-plane plan/version storage is reused."""
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


def sqlite_schema():
    # SQLite is development-only. Production uses explicit Alembic migrations.
    statements = [
        'CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,timestamp TEXT NOT NULL,payload TEXT NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS cp_plans (id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,objective TEXT NOT NULL,
           owner_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(tenant_id,id))''',
        '''CREATE TABLE IF NOT EXISTS cp_plan_versions (id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,
           version INTEGER NOT NULL CHECK(version>=1),identity_digest TEXT NOT NULL,targets TEXT NOT NULL,parameters TEXT NOT NULL,
           policy_digest TEXT NOT NULL,evidence_digest TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'draft',created_by_hash TEXT NOT NULL,
           created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,plan_id,version),UNIQUE(tenant_id,id),
           FOREIGN KEY(tenant_id,plan_id) REFERENCES cp_plans(tenant_id,id))''',
        'CREATE UNIQUE INDEX IF NOT EXISTS engineering_scan_owner ON scans(id,tenant_id)',
    ]
    for ddl in TABLES.values():
        for kind in ('uuid', 'jsonb', 'timestamptz'):
            ddl = ddl.replace(kind, 'TEXT')
        statements.append(ddl.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS '))
    statements.extend(ddl.replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ') for ddl in INDEXES)
    for table in ('engineering_members', 'engineering_plan_links', 'engineering_plan_targets', 'engineering_commands', 'engineering_events'):
        for operation in ('UPDATE', 'DELETE'):
            statements.append(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Engineering history is append-only'); END")
    return ';\n'.join(statements) + ';'
