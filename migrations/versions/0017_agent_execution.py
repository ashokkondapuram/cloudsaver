"""Approval-bound agent tasks and append-only execution audit."""
revision = '0017_agent_execution'
down_revision = '0016_nextgen_savings'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE agent_tasks (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, provider varchar(16) NOT NULL,
        scope_id varchar(128) NOT NULL, resource_id text NOT NULL, scan_id uuid NOT NULL,
        request_key uuid NOT NULL, fingerprint char(64) NOT NULL, state varchar(32) NOT NULL,
        version integer NOT NULL CHECK(version>0), payload jsonb NOT NULL, actor char(64) NOT NULL,
        created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
        UNIQUE(tenant_id,request_key), UNIQUE(id,tenant_id), CHECK(octet_length(payload::text)<=64000),
        CHECK(state IN ('draft_queued','drafting','awaiting_approval','approved','running','succeeded',
          'failed','rejected','cancelled','cancel_requested','needs_reconciliation','approval_expired')),
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT)''')
    op.execute('CREATE INDEX ix_agent_queue ON agent_tasks(tenant_id,state,created_at,id)')
    op.execute('''CREATE TABLE agent_task_events (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, task_id uuid NOT NULL, version integer NOT NULL,
        action varchar(60) NOT NULL, actor varchar(128) NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL,
        UNIQUE(task_id,version), CHECK(octet_length(payload::text)<=20000),
        FOREIGN KEY(task_id,tenant_id) REFERENCES agent_tasks(id,tenant_id) ON DELETE RESTRICT)''')
    for table in ('agent_tasks', 'agent_task_events'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)")
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT SELECT,INSERT ON {table} TO cloudsaver_app')
    op.execute('GRANT UPDATE(state,version,payload,updated_at) ON agent_tasks TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.execute('DROP TABLE agent_task_events')
    op.execute('DROP TABLE agent_tasks')
