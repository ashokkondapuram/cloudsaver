"""Durable tenant-scoped GitOps request leases and idempotency."""
revision = '0006_gitops_requests'
down_revision = '0005_cloud_findings'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE public.gitops_requests (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, scan_id uuid NOT NULL,
        idempotency_digest varchar(64) NOT NULL, fingerprint varchar(64) NOT NULL,
        target_id varchar(40) NOT NULL, repository varchar(201) NOT NULL, branch varchar(120) NOT NULL,
        status varchar(16) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','publishing','open','uncertain')),
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0 AND attempts <= 4),
        lease_token uuid, lease_until double precision NOT NULL DEFAULT 0,
        result jsonb, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_gitops_key UNIQUE(tenant_id,idempotency_digest),
        CONSTRAINT fk_gitops_scan_owner FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('CREATE INDEX ix_gitops_owner_created ON gitops_requests(tenant_id,created_at)')
    op.execute('ALTER TABLE gitops_requests ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE gitops_requests FORCE ROW LEVEL SECURITY')
    op.execute("""CREATE POLICY tenant_isolation_gitops ON gitops_requests FOR ALL
        USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)
        WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)""")
    op.execute('GRANT SELECT,INSERT,UPDATE ON gitops_requests TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.drop_table('gitops_requests')
