"""Add normalized non-Azure findings without weakening legacy subscription FKs."""
revision = '0005_cloud_findings'
down_revision = '0004_merge_hardening'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE public.cloud_findings (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL,
        scan_id uuid NOT NULL,
        cloud_provider varchar(16) NOT NULL CHECK (cloud_provider IN ('aws','gcp','kubernetes')),
        scope_id varchar(256) NOT NULL,
        resource_id text NOT NULL,
        rule_id varchar(64) NOT NULL,
        payload jsonb NOT NULL,
        observed_at timestamptz NOT NULL,
        CONSTRAINT fk_cloud_findings_scan_owner FOREIGN KEY (scan_id,tenant_id)
            REFERENCES public.scans(id,tenant_id) ON DELETE RESTRICT,
        CONSTRAINT uq_cloud_findings_identity UNIQUE(scan_id,cloud_provider,resource_id,rule_id)
    )''')
    op.execute('CREATE INDEX ix_cloud_findings_owner_observed ON public.cloud_findings(tenant_id,observed_at)')
    op.execute('ALTER TABLE public.cloud_findings ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE public.cloud_findings FORCE ROW LEVEL SECURITY')
    op.execute("""CREATE POLICY tenant_isolation_cloud_findings ON public.cloud_findings FOR ALL
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)""")
    op.execute('GRANT SELECT,INSERT ON public.cloud_findings TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.drop_table('cloud_findings')
