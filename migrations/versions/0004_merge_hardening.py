"""Reconcile verified v0.2 scan links with the Drive billing/worker lineage.

Both prior paths remain upgradeable; revision history is not rewritten.
"""
revision = '0004_merge_hardening'
down_revision = ('0002_scan_findings', '0003_scan_jobs')
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql
    op.add_column('scan_jobs', sa.Column('lease_token', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_scan_jobs_scan_owner', 'scan_jobs', 'scans', ['scan_id','tenant_id'], ['id','tenant_id'], ondelete='RESTRICT')


def downgrade():
    from alembic import op
    op.drop_constraint('fk_scan_jobs_scan_owner', 'scan_jobs', type_='foreignkey')
    op.drop_column('scan_jobs', 'lease_token')
