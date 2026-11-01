"""0033 — lease owner, fence, and expiry for platform outbox intents."""
from alembic import op

revision = "0033_platform_outbox_lease"
down_revision = "0032_v3_semantic_embeddings"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE platform_outbox_intents ADD COLUMN IF NOT EXISTS lease_owner varchar(64)")
    op.execute(
        "ALTER TABLE platform_outbox_intents ADD COLUMN IF NOT EXISTS lease_fence integer NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE platform_outbox_intents ADD COLUMN IF NOT EXISTS lease_until timestamptz")
    op.execute(
        "CREATE INDEX IF NOT EXISTS platform_outbox_expired_lease "
        "ON platform_outbox_intents(tenant_id,kind,lease_until) WHERE status='leased'"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS platform_outbox_expired_lease")
    op.execute("ALTER TABLE platform_outbox_intents DROP COLUMN IF EXISTS lease_until")
    op.execute("ALTER TABLE platform_outbox_intents DROP COLUMN IF EXISTS lease_fence")
    op.execute("ALTER TABLE platform_outbox_intents DROP COLUMN IF EXISTS lease_owner")
