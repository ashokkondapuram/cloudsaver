"""Publish the eight guarded Kubernetes review contracts."""
revision='i0012_kubernetes_rules'
down_revision='i0011_ai_foundry_policy'
branch_labels=depends_on=None


def upgrade():
    from alembic import op
    import sqlalchemy as sa
    from identity.analysis.kubernetes import DEFINITIONS
    op.execute('ALTER TABLE analysis.rule_catalog NO FORCE ROW LEVEL SECURITY')
    for rid,category,kind,name,pillar in DEFINITIONS:
        op.get_bind().execute(sa.text('''INSERT INTO analysis.rule_catalog
            (id,provider,service_category,resource_type,name,description,pillar,status,created_by,updated_by)
            VALUES (:id,'kubernetes',:category,:kind,:name,'Guarded advisory review; missing multi-source evidence remains unknown.',:pillar,'published','migration','migration')
            ON CONFLICT(id) DO NOTHING'''),dict(id=rid,category=category,kind=kind,name=name,pillar=pillar))
    op.execute('ALTER TABLE analysis.rule_catalog FORCE ROW LEVEL SECURITY')


def downgrade():
    # Retain catalog identities referenced by audit records and customer policy history.
    pass
