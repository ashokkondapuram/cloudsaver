"""0037 — allow running-scan incremental persistence (UPDATE payload, abandon DELETE)."""
from alembic import op

revision = "0037_scans_update_delete_grants"
down_revision = "0036_typed_resource_tables"
branch_labels = depends_on = None


def upgrade():
    op.execute("GRANT UPDATE, DELETE ON public.scans TO cloudsaver_app")


def downgrade():
    op.execute("REVOKE UPDATE, DELETE ON public.scans FROM cloudsaver_app")
