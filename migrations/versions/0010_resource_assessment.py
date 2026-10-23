"""Per-resource AI batches, follow-up questions and reviewer decisions."""
revision = '0010_resource_assessment'
down_revision = '0009_enterprise_evidence'
branch_labels = None
depends_on = None

TABLES = ('ai_batches', 'ai_batch_items', 'ai_followups', 'resource_decisions')


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE ai_batches (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, request_key uuid NOT NULL, scan_id uuid NOT NULL,
        target_id varchar(64) NOT NULL,
        status varchar(24) NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','running','waiting_for_budget','completed','cancelled')),
        total integer NOT NULL CHECK(total BETWEEN 1 AND 500), resume_after timestamptz,
        actor char(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(tenant_id,request_key), UNIQUE(id,tenant_id),
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('''CREATE UNIQUE INDEX ux_ai_batch_active ON ai_batches(tenant_id,scan_id)
        WHERE status IN ('queued','running','waiting_for_budget')''')
    op.execute('CREATE INDEX ix_ai_batch_history ON ai_batches(tenant_id,created_at DESC,id DESC)')
    op.execute('''CREATE TABLE ai_batch_items (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, batch_id uuid NOT NULL, resource_key char(64) NOT NULL,
        evidence_digest char(64) NOT NULL,
        status varchar(16) NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','running','completed','failed','skipped','uncertain','cancelled')),
        attempt_id uuid, reason varchar(40), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(batch_id,resource_key),
        FOREIGN KEY(batch_id,tenant_id) REFERENCES ai_batches(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('CREATE INDEX ix_ai_batch_item_queue ON ai_batch_items(tenant_id,batch_id,status)')
    op.execute('''CREATE TABLE ai_followups (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, scan_id uuid NOT NULL, resource_key char(64) NOT NULL,
        attempt_id uuid NOT NULL, question varchar(500) NOT NULL, actor char(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT,
        FOREIGN KEY(attempt_id,tenant_id) REFERENCES ai_inference_attempts(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('CREATE INDEX ix_ai_followup_resource ON ai_followups(tenant_id,scan_id,resource_key,created_at)')
    op.execute('''CREATE TABLE resource_decisions (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, resource_key char(64) NOT NULL, scan_id uuid NOT NULL,
        decision varchar(16) NOT NULL CHECK(decision IN ('accept','dismiss','defer')),
        note varchar(1000) NOT NULL DEFAULT '', defer_until date, evidence_digest char(64) NOT NULL,
        actor char(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK((decision='defer') OR defer_until IS NULL),
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('CREATE INDEX ix_resource_decision_latest ON resource_decisions(tenant_id,resource_key,created_at DESC,id DESC)')
    for table in TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"""CREATE POLICY tenant_isolation_{table} ON {table} FOR ALL
            USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)
            WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)""")
        op.execute(f'GRANT SELECT,INSERT ON {table} TO cloudsaver_app')
    op.execute('GRANT UPDATE(status,resume_after,updated_at) ON ai_batches TO cloudsaver_app')
    op.execute('GRANT UPDATE(status,attempt_id,reason,updated_at) ON ai_batch_items TO cloudsaver_app')


def downgrade():
    from alembic import op
    for table in reversed(TABLES):
        op.drop_table(table)
