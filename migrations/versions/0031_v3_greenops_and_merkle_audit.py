from app.v3_greenops_audit_schema import INDEXES, TABLES

revision = "0031_v3_greenops_and_merkle_audit"
down_revision = "0030_v3_saas_focus_and_ebpf_flows"
branch_labels = depends_on = None


def upgrade():
    from alembic import op

    owner = "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
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


def downgrade():
    from alembic import op
    from sqlalchemy import text

    db = op.get_bind()
    op.execute("LOCK TABLE " + ",".join(TABLES) + " IN ACCESS EXCLUSIVE MODE")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        if db.execute(text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar():
            raise RuntimeError(f"Refusing downgrade with rows in {table}")
    for table in reversed(list(TABLES)):
        op.execute(f"DROP TABLE {table}")
