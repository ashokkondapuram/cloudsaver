"""Tenant-isolated savings cases, append-only events and authenticated collector receipts."""
revision='0016_nextgen_savings'
down_revision='0015_ai_foundry_diagnostics'
branch_labels=depends_on=None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE savings_cases (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,provider varchar(16) NOT NULL,scope_id varchar(128) NOT NULL,
        resource_id text NOT NULL,baseline_scan_id uuid NOT NULL,request_key uuid NOT NULL,fingerprint char(64) NOT NULL,
        state varchar(40) NOT NULL CHECK(state IN ('reviewed','accepted_for_investigation','scheduled','rejected','deferred','verified_completed','reopened_on_regression')),
        version integer NOT NULL DEFAULT 1 CHECK(version>0),payload jsonb NOT NULL,verification jsonb,
        actor char(64) NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
        UNIQUE(tenant_id,request_key),UNIQUE(id,tenant_id),CHECK(octet_length(payload::text)<=16000),
        FOREIGN KEY(baseline_scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT)''')
    op.execute('CREATE INDEX ix_savings_case_scope ON savings_cases(tenant_id,provider,scope_id,updated_at DESC,id DESC)')
    op.execute('''CREATE TABLE savings_case_events (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,case_id uuid NOT NULL,action varchar(60) NOT NULL,
        version integer NOT NULL,payload jsonb NOT NULL,actor char(64) NOT NULL,created_at timestamptz NOT NULL,
        UNIQUE(case_id,version),CHECK(octet_length(payload::text)<=16000),
        FOREIGN KEY(case_id,tenant_id) REFERENCES savings_cases(id,tenant_id) ON DELETE RESTRICT)''')
    op.execute('''CREATE TABLE savings_evidence_receipts (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,receipt_key uuid NOT NULL,source_id varchar(60) NOT NULL,
        provider varchar(16) NOT NULL,scope_id varchar(128) NOT NULL,resource_id text NOT NULL,kind varchar(16) NOT NULL CHECK(kind IN ('audit','billing','slo')),
        fingerprint char(64) NOT NULL,payload jsonb NOT NULL,issued_at timestamptz NOT NULL,created_at timestamptz NOT NULL,
        UNIQUE(tenant_id,source_id,receipt_key),UNIQUE(id,tenant_id),CHECK(octet_length(payload::text)<=16000))''')
    op.execute('CREATE INDEX ix_savings_receipt_resource ON savings_evidence_receipts(tenant_id,provider,scope_id,kind,issued_at DESC)')
    op.execute('''CREATE TABLE savings_verified_actions (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,case_id uuid NOT NULL,event_key char(64) NOT NULL,
        receipt_id uuid NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,event_key),
        FOREIGN KEY(case_id,tenant_id) REFERENCES savings_cases(id,tenant_id) ON DELETE RESTRICT,
        FOREIGN KEY(receipt_id,tenant_id) REFERENCES savings_evidence_receipts(id,tenant_id) ON DELETE RESTRICT)''')
    for table in ('savings_cases','savings_case_events','savings_evidence_receipts','savings_verified_actions'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)")
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT SELECT,INSERT ON {table} TO cloudsaver_app')
    op.execute('GRANT UPDATE(state,version,payload,verification,updated_at) ON savings_cases TO cloudsaver_app')


def downgrade():
    from alembic import op
    for table in ('savings_verified_actions','savings_case_events','savings_evidence_receipts','savings_cases'):op.execute('DROP TABLE '+table)
