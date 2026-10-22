"""Link normalized findings to their tenant-owned scan without rewriting history.

Revision ID: 0002_scan_findings
Revises: 0001_domain
"""
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_scan_findings'
down_revision = '0001_domain'
branch_labels = None
depends_on = None


def upgrade():
    # Also supports installations initialized without the Compose entrypoint.
    schema = Path(__file__).resolve().parents[2] / 'database' / '001_schema.sql'
    for statement in schema.read_text().split(';'):
        if statement.strip():
            op.execute(statement)
    op.create_unique_constraint('uq_scans_id_tenant', 'scans', ['id', 'tenant_id'])
    # Null preserves any pre-existing domain rows, whose source scan is unknown.
    op.add_column('waste_findings', sa.Column('scan_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_waste_findings_scan_owner', 'waste_findings', 'scans',
                          ['scan_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='RESTRICT')
    op.create_unique_constraint('uq_waste_findings_scan_resource_rule', 'waste_findings',
                               ['scan_id', 'resource_id', 'rule_id'])


def downgrade():
    op.drop_constraint('uq_waste_findings_scan_resource_rule', 'waste_findings', type_='unique')
    op.drop_constraint('fk_waste_findings_scan_owner', 'waste_findings', type_='foreignkey')
    op.drop_column('waste_findings', 'scan_id')
    op.drop_constraint('uq_scans_id_tenant', 'scans', type_='unique')
    # Scan snapshots predate Alembic and must survive a domain downgrade.
