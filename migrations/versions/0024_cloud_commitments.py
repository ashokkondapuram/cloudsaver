"""Append-only provider commitment snapshots (reservations, savings plans, committed use discounts)."""
revision = '0024_cloud_commitments'
down_revision = '0023_risk_governance'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE cloud_commitment_snapshots (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,provider varchar(16) NOT NULL,scope_id text NOT NULL,
        job_id uuid,status varchar(40) NOT NULL,payload jsonb NOT NULL,observed_at timestamptz NOT NULL)''')
    op.execute('CREATE INDEX cloud_commitment_snapshots_owner ON cloud_commitment_snapshots(tenant_id,provider,scope_id,observed_at DESC)')
    op.execute('ALTER TABLE cloud_commitment_snapshots ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE cloud_commitment_snapshots FORCE ROW LEVEL SECURITY')
    owner = "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
    op.execute(f'CREATE POLICY tenant_isolation ON cloud_commitment_snapshots USING ({owner}) WITH CHECK ({owner})')
    op.execute('REVOKE ALL ON cloud_commitment_snapshots FROM PUBLIC')
    op.execute('GRANT SELECT,INSERT ON cloud_commitment_snapshots TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.execute('DROP TABLE cloud_commitment_snapshots')
