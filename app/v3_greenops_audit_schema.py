"""v3.0 GreenOps and Merkle audit tables (migration 0031)."""

TABLES = {
    "resource_carbon_metrics": """CREATE TABLE resource_carbon_metrics (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        canonical_resource_id text NOT NULL,
        provider varchar(20) NOT NULL,
        region varchar(40) NOT NULL,
        energy_kwh numeric(20,6) NOT NULL,
        grid_carbon_intensity_gco2_kwh numeric(20,6) NOT NULL,
        scope2_gco2e numeric(20,6) NOT NULL,
        scope3_embodied_gco2e numeric(20,6) NOT NULL,
        observation_window tstzrange NOT NULL,
        created_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id)
    )""",
    "tamper_evident_audit_chain": """CREATE TABLE tamper_evident_audit_chain (
        tenant_id uuid NOT NULL,
        sequence_id bigserial NOT NULL,
        event_category varchar(60) NOT NULL,
        actor_identity text NOT NULL,
        payload_digest_sha256 char(64) NOT NULL,
        previous_chain_hash char(64) NOT NULL,
        entry_chain_hash char(64) NOT NULL,
        recorded_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,sequence_id)
    )""",
}
INDEXES = (
    "CREATE INDEX carbon_resource ON resource_carbon_metrics(tenant_id,canonical_resource_id)",
    "CREATE INDEX merkle_chain_time ON tamper_evident_audit_chain(tenant_id,recorded_at DESC)",
)


def sqlite_schema():
    statements = []
    for name, ddl in TABLES.items():
        for kind in ("uuid", "jsonb", "timestamptz", "tstzrange", "bigserial"):
            ddl = ddl.replace(kind, "TEXT")
        ddl = ddl.replace("numeric(20,6)", "TEXT")
        if name == "tamper_evident_audit_chain":
            ddl = """CREATE TABLE IF NOT EXISTS tamper_evident_audit_chain (
        tenant_id TEXT NOT NULL,
        sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_category TEXT NOT NULL,
        actor_identity TEXT NOT NULL,
        payload_digest_sha256 TEXT NOT NULL,
        previous_chain_hash TEXT NOT NULL,
        entry_chain_hash TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    )"""
        statements.append(ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ") if "IF NOT EXISTS" not in ddl else ddl)
    statements.extend(
        ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ") for ddl in INDEXES
    )
    return ";\n".join(statements) + ";"
