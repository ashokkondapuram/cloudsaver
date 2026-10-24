"""Typed per-rule parameters and eight evidence-based Azure reviews."""
revision = 'i0010_analysis_policy'
down_revision = 'i0009_entitlements_changed'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    import sqlalchemy as sa
    from identity.analysis.contracts import DEFINITIONS
    op.execute("ALTER TABLE analysis.workspace_rules ADD COLUMN parameters jsonb NOT NULL DEFAULT '{}'::jsonb")
    # Table-owner seed writes occur under the migration transaction's exclusive DDL lock.
    # Failure rolls back this flag with the data; runtime roles retain forced RLS after commit.
    op.execute('ALTER TABLE analysis.rule_catalog NO FORCE ROW LEVEL SECURITY')
    for rule_id, category, kind, name, _ in DEFINITIONS:
        op.get_bind().execute(sa.text('''INSERT INTO analysis.rule_catalog
            (id, provider, service_category, resource_type, name, description, pillar, status, created_by, updated_by)
            VALUES (:id, 'azure', :category, :kind, :name,
            'Evidence-based advisory review; missing history or telemetry returns insufficient evidence.',
            'cost', 'published', 'migration', 'migration') ON CONFLICT (id) DO NOTHING'''),
            dict(id=rule_id, category=category, kind=kind, name=name))
    op.execute('ALTER TABLE analysis.rule_catalog FORCE ROW LEVEL SECURITY')


def downgrade():
    from alembic import op
    op.execute('ALTER TABLE analysis.workspace_rules DROP COLUMN parameters')
