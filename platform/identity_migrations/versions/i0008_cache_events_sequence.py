"""Let the application role allocate cache event sequence numbers."""
revision = 'i0008_cache_events_sequence'
down_revision = 'i0007_client_access'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('GRANT USAGE ON SEQUENCE identity.cache_events_seq_seq TO identity_app')


def downgrade():
    from alembic import op
    op.execute('REVOKE USAGE ON SEQUENCE identity.cache_events_seq_seq FROM identity_app')
