"""Semantic resource embeddings (portable jsonb; pgvector index optional in migration 0032)."""

TABLES = {
    "semantic_resource_embeddings": """CREATE TABLE semantic_resource_embeddings (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        cloud_resource_id text NOT NULL,
        model_id varchar(80) NOT NULL,
        dimensions integer NOT NULL CHECK(dimensions > 0 AND dimensions <= 4096),
        embedding jsonb NOT NULL,
        source_manifest text,
        created_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id),
        UNIQUE(tenant_id,cloud_resource_id,model_id)
    )""",
}
INDEXES = (
    "CREATE INDEX semantic_embeddings_resource ON semantic_resource_embeddings(tenant_id,cloud_resource_id)",
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
