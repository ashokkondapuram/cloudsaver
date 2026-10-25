"""Versioned ownership, accountable anomalies and evidence-backed financial claims."""

revision = "0022_financial_outcomes"
down_revision = "0021_billing_jobs"
branch_labels = depends_on = None


def upgrade():
    from alembic import op

    old = "'reviewed','accepted_for_investigation','scheduled','rejected','deferred','verified_completed','reopened_on_regression'"
    new = "'detected','assigned','approved','implemented','validated','financially_reconciled'"
    op.execute("ALTER TABLE savings_cases DROP CONSTRAINT savings_cases_state_check")
    op.execute(
        f"ALTER TABLE savings_cases ADD CONSTRAINT savings_cases_state_check CHECK(state IN ({old},{new}))"
    )
    op.execute("""CREATE TABLE finops_ownership (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,provider varchar(16) NOT NULL,scope_id varchar(128) NOT NULL,
        resource_id text NOT NULL,version integer NOT NULL,payload jsonb NOT NULL,actor char(64) NOT NULL,created_at timestamptz NOT NULL,
        UNIQUE(tenant_id,provider,scope_id,resource_id,version))""")
    op.execute("""CREATE TABLE finops_anomalies (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,fingerprint char(64) NOT NULL,provider varchar(16) NOT NULL,
        scope_id varchar(128) NOT NULL,resource_id text,currency char(3) NOT NULL,state varchar(32) NOT NULL,
        version integer NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
        UNIQUE(tenant_id,fingerprint),UNIQUE(id,tenant_id))""")
    op.execute("""CREATE TABLE finops_anomaly_events (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,anomaly_id uuid NOT NULL,version integer NOT NULL,action varchar(40) NOT NULL,
        payload jsonb NOT NULL,actor char(64) NOT NULL,created_at timestamptz NOT NULL,
        UNIQUE(tenant_id,anomaly_id,version),FOREIGN KEY(anomaly_id,tenant_id) REFERENCES finops_anomalies(id,tenant_id))""")
    op.execute("""CREATE TABLE finops_suppressions (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,provider varchar(16) NOT NULL,scope_id varchar(128) NOT NULL,resource_id text,
        start_date date NOT NULL,end_date date NOT NULL,payload jsonb NOT NULL,actor char(64) NOT NULL,created_at timestamptz NOT NULL,
        CHECK(end_date>start_date))""")
    op.execute("""CREATE TABLE savings_financial_claims (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,case_id uuid NOT NULL,provider varchar(16) NOT NULL,scope_id varchar(128) NOT NULL,
        resource_id text NOT NULL,currency char(3) NOT NULL,period_start date NOT NULL,period_end date NOT NULL,
        receipt_id uuid NOT NULL,revision integer NOT NULL DEFAULT 1,amount numeric(30,8) NOT NULL,evidence jsonb NOT NULL,ledger_digest char(64) NOT NULL,created_at timestamptz NOT NULL,
        UNIQUE(tenant_id,case_id,receipt_id),CHECK(period_end>period_start),
        FOREIGN KEY(case_id,tenant_id) REFERENCES savings_cases(id,tenant_id),
        FOREIGN KEY(receipt_id,tenant_id) REFERENCES savings_evidence_receipts(id,tenant_id))""")
    for table in (
        "finops_ownership",
        "finops_anomalies",
        "finops_anomaly_events",
        "finops_suppressions",
        "savings_financial_claims",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        policy = (
            "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
        )
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({policy}) WITH CHECK ({policy})"
        )
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"GRANT SELECT,INSERT ON {table} TO cloudsaver_app")
        op.execute(f"CREATE INDEX {table}_tenant ON {table}(tenant_id,created_at DESC)")
    op.execute(
        "GRANT UPDATE(state,version,payload,updated_at) ON finops_anomalies TO cloudsaver_app"
    )


def downgrade():
    from alembic import op
    from sqlalchemy import text

    db = op.get_bind()
    tables = (
        "savings_financial_claims",
        "finops_anomaly_events",
        "finops_anomalies",
        "finops_suppressions",
        "finops_ownership",
    )
    # Only the migration owner can inspect global history. The enclosing migration
    # transaction restores FORCE on any refusal; runtime privileges never change.
    for table in (*tables, "savings_cases"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    if (
        any(
            db.execute(text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar()
            for table in tables
        )
        or db.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM savings_cases WHERE payload->>'schema_version'='2')"
            )
        ).scalar()
    ):
        raise RuntimeError(
            "Financial and ownership audit history requires a reviewed data-preserving rollback"
        )
    op.execute("ALTER TABLE savings_cases FORCE ROW LEVEL SECURITY")
    for table in tables:
        op.execute(f"DROP TABLE {table}")
    op.execute("ALTER TABLE savings_cases DROP CONSTRAINT savings_cases_state_check")
    op.execute(
        "ALTER TABLE savings_cases ADD CONSTRAINT savings_cases_state_check CHECK(state IN ('reviewed','accepted_for_investigation','scheduled','rejected','deferred','verified_completed','reopened_on_regression'))"
    )
