"""Publish 36-family review catalog on top of the actual i0012 baseline."""
revision='i0013_multicloud_analysis_catalog'
down_revision='i0012_kubernetes_rules'
branch_labels=depends_on=None

def upgrade():
    from alembic import op
    import sqlalchemy as sa
    from identity.analysis.multicloud import definitions
    op.execute('ALTER TABLE identity.alembic_version ALTER COLUMN version_num TYPE varchar(80)')
    op.execute('ALTER TABLE analysis.rule_catalog NO FORCE ROW LEVEL SECURITY')
    for rid,provider,category,kind,name,pillar,bounds in definitions():
        op.get_bind().execute(sa.text('''INSERT INTO analysis.rule_catalog
          (id,provider,service_category,resource_type,name,description,pillar,status,created_by,updated_by)
          VALUES(:id,:provider,:category,:kind,:name,'Evidence-bound review. Missing telemetry, history or target compatibility remains unknown.',:pillar,'published','migration','migration')
          ON CONFLICT(id) DO NOTHING'''),dict(id=rid,provider=provider,category=category,kind=kind,name=name,pillar=pillar))
    op.execute('ALTER TABLE analysis.rule_catalog FORCE ROW LEVEL SECURITY')

def downgrade():
    # Preserve identities referenced by customer settings and audit records.
    pass
