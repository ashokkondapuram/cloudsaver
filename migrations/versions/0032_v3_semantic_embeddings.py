"""Semantic embeddings table (0032); optional pgvector column when extension is present."""
from app.v3_semantic_schema import INDEXES, TABLES

revision = "0032_v3_semantic_embeddings"
down_revision = "0031_v3_greenops_and_merkle_audit"
branch_labels = depends_on = None


def upgrade():
    from alembic import op

    owner = "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
    # Extensions are provisioned by a database administrator, never the runtime or migration owner.
    from sqlalchemy import text
    vector_enabled = op.get_bind().execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar()
    for table, ddl in TABLES.items():
        op.execute(ddl)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({owner}) WITH CHECK ({owner})"
        )
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO cloudsaver_app")
    for ddl in INDEXES:
        op.execute(ddl)
    if not vector_enabled:
        return
    op.execute(
        "ALTER TABLE semantic_resource_embeddings ADD COLUMN IF NOT EXISTS embedding_vector vector(1536)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS semantic_embeddings_vector_hnsw "
        "ON semantic_resource_embeddings USING hnsw (embedding_vector vector_cosine_ops)"
    )


def downgrade():
    from alembic import op
    from sqlalchemy import text

    db = op.get_bind()
    op.execute("LOCK TABLE " + ",".join(TABLES) + " IN ACCESS EXCLUSIVE MODE")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        if db.execute(text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar():
            raise RuntimeError(f"Refusing downgrade with rows in {table}")
    op.execute("DROP INDEX IF EXISTS semantic_embeddings_vector_hnsw")
    op.execute("ALTER TABLE semantic_resource_embeddings DROP COLUMN IF EXISTS embedding_vector")
    for table in reversed(list(TABLES)):
        op.execute(f"DROP TABLE {table}")
