"""PostgreSQL feature detection for operator cloud-status and worker startup."""
from database.connection import connect as pooled_connect

CAPABILITY_QUERIES = {
    'resource_type_catalog': (
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='resource_type_catalog'"
    ),
    'typed_resource_tables': (
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='azure_compute_disks'"
    ),
    'platform_outbox_lease': (
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='platform_outbox_intents' AND column_name='lease_fence'"
    ),
}


def postgres_schema_capabilities(database_url):
    if not database_url:
        return {}
    with pooled_connect(database_url, connect_timeout=5) as db:
        return {
            name: bool(db.execute(sql).fetchone())
            for name, sql in CAPABILITY_QUERIES.items()
        }


def require_platform_outbox_lease_columns(db):
    """Workers must not dispatch drift/GitOps outbox rows without migration 0033."""
    if not db.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='platform_outbox_intents'"
    ).fetchone():
        return
    if not db.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='platform_outbox_intents' AND column_name='lease_fence'"
    ).fetchone():
        raise ValueError('Apply Alembic migration 0033_platform_outbox_lease before running workers')
