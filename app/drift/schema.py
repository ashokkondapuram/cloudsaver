"""PostgreSQL drift + GitOps remediation outbox (migration 0028)."""

TABLES = {
    "platform_outbox_intents": """CREATE TABLE platform_outbox_intents (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        kind varchar(40) NOT NULL,
        idempotency_key char(64) NOT NULL,
        payload jsonb NOT NULL,
        status varchar(20) NOT NULL DEFAULT 'pending',
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0 AND attempts <= 8),
        last_error varchar(120),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id),
        UNIQUE(tenant_id,idempotency_key),
        CHECK(status IN ('pending','leased','completed','failed')),
        CHECK(kind IN ('DRIFT_INSPECT_RESOURCE','GITOPS_CREATE_PR'))
    )""",
    "gitops_remediation_requests": """CREATE TABLE gitops_remediation_requests (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        idempotency_key char(64) NOT NULL,
        canonical_resource_id text NOT NULL,
        status varchar(32) NOT NULL DEFAULT 'QUEUED',
        payload jsonb NOT NULL,
        result jsonb,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id),
        UNIQUE(tenant_id,idempotency_key),
        CHECK(status IN ('QUEUED','PROCESSING','OPEN','REPO_DRIFT_REINDEX_REQUIRED','FAILED','UNCERTAIN'))
    )""",
}
INDEXES = (
    "CREATE INDEX platform_outbox_pending ON platform_outbox_intents(tenant_id,created_at,id) WHERE status='pending'",
    "CREATE INDEX gitops_remediation_owner ON gitops_remediation_requests(tenant_id,created_at DESC,id DESC)",
)


def sqlite_schema():
    statements = []
    for ddl in TABLES.values():
        for kind in ("uuid", "jsonb", "timestamptz"):
            ddl = ddl.replace(kind, "TEXT")
        statements.append(ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "))
    statements.extend(
        ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ") for ddl in INDEXES
    )
    return ";\n".join(statements) + ";"
