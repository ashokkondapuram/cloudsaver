"""Tenant-isolated governance records and append-only evidence history."""

from alembic import op
from sqlalchemy import text

revision = "0023_risk_governance"
down_revision = "0022_financial_outcomes"
branch_labels = depends_on = None
TABLES = (
    "gov_controls",
    "gov_grants",
    "gov_findings",
    "gov_risks",
    "gov_exceptions",
    "gov_assessments",
    "gov_receipts",
    "gov_actions",
    "gov_events",
    "gov_monitor",
)


def upgrade():
    op.execute(
        "CREATE TABLE gov_controls (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,control_key text NOT NULL,version integer NOT NULL,payload jsonb NOT NULL,actor char(64) NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,control_key,version))"
    )
    op.execute(
        "CREATE TABLE gov_grants (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,subject_id text NOT NULL,role text NOT NULL,version integer NOT NULL,payload jsonb NOT NULL,actor char(64) NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,subject_id,role,version))"
    )
    op.execute(
        "CREATE TABLE gov_findings (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,provider text NOT NULL,scope_id text NOT NULL,resource_id text NOT NULL,control_key text NOT NULL,state text NOT NULL,version integer NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,UNIQUE(id,tenant_id),UNIQUE(tenant_id,provider,scope_id,resource_id,control_key))"
    )
    op.execute(
        "CREATE TABLE gov_risks (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,state text NOT NULL,version integer NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,UNIQUE(id,tenant_id))"
    )
    op.execute(
        "CREATE TABLE gov_exceptions (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,finding_id uuid NOT NULL,state text NOT NULL,version integer NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,UNIQUE(id,tenant_id),FOREIGN KEY(finding_id,tenant_id) REFERENCES gov_findings(id,tenant_id))"
    )
    op.execute(
        "CREATE TABLE gov_assessments (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,finding_id uuid NOT NULL,ordinal integer NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,ordinal))"
    )
    op.execute(
        "CREATE TABLE gov_receipts (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,finding_id uuid NOT NULL,source_id text NOT NULL,receipt_key uuid NOT NULL,kind text NOT NULL,ordinal integer NOT NULL,fingerprint char(64) NOT NULL,envelope jsonb NOT NULL,signature_hex char(64) NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,source_id,receipt_key),UNIQUE(tenant_id,ordinal),FOREIGN KEY(finding_id,tenant_id) REFERENCES gov_findings(id,tenant_id))"
    )
    op.execute(
        "CREATE TABLE gov_actions (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,finding_id uuid NOT NULL,event_key char(64) NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,event_key),FOREIGN KEY(finding_id,tenant_id) REFERENCES gov_findings(id,tenant_id))"
    )
    op.execute(
        "CREATE TABLE gov_events (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,entity_type text NOT NULL,entity_id text NOT NULL,version integer NOT NULL,payload jsonb NOT NULL,previous_hash char(64) NOT NULL,event_hash char(64) NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,entity_type,entity_id,version))"
    )
    op.execute(
        "CREATE TABLE gov_monitor (tenant_id uuid PRIMARY KEY,payload jsonb NOT NULL,updated_at timestamptz NOT NULL)"
    )
    for table in TABLES:
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
        if table != "gov_monitor":
            op.execute(
                f"CREATE INDEX {table}_tenant ON {table}(tenant_id,created_at DESC)"
            )
    for table in ("gov_findings", "gov_risks", "gov_exceptions"):
        op.execute(
            f"GRANT UPDATE(state,version,payload,updated_at) ON {table} TO cloudsaver_app"
        )
    op.execute("GRANT UPDATE(payload,updated_at) ON gov_monitor TO cloudsaver_app")

    op.execute(
        "CREATE INDEX gov_receipts_target ON gov_receipts(tenant_id,finding_id,kind,ordinal DESC)"
    )
    op.execute(
        "CREATE INDEX gov_assessments_finding ON gov_assessments(tenant_id,finding_id,ordinal)"
    )
    op.execute(
        "CREATE INDEX gov_exceptions_finding ON gov_exceptions(tenant_id,finding_id,created_at)"
    )


def downgrade():
    db = op.get_bind()
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    if any(
        db.execute(text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar()
        for table in TABLES
    ):
        raise RuntimeError(
            "Governance history requires a reviewed data-preserving rollback"
        )
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
