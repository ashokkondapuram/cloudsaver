"""Transactional dispatch, delivery leases and append-only operational audit."""
revision = '0007_delivery_outbox'
down_revision = '0006_gitops_requests'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('ALTER TABLE scan_jobs DROP CONSTRAINT ck_scan_jobs_notification')
    op.execute("ALTER TABLE scan_jobs ADD CONSTRAINT ck_scan_jobs_notification CHECK(notification_status IN ('not_requested','queued','sent','failed'))")
    op.execute('ALTER TABLE scan_jobs ADD CONSTRAINT uq_scan_job_owner UNIQUE(id,tenant_id)')
    op.execute('''CREATE TABLE delivery_events (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, kind varchar(16) NOT NULL CHECK(kind IN ('scan','notification')),
        dedupe_key varchar(64) NOT NULL, job_id uuid, scan_id uuid, target_id varchar(40), target_fingerprint varchar(64),
        payload jsonb NOT NULL CHECK(octet_length(payload::text) <= 16000),
        status varchar(16) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','leased','published','delivered','dead_letter')),
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 8),
        replay_count integer NOT NULL DEFAULT 0 CHECK(replay_count BETWEEN 0 AND 3),
        lease_token uuid, lease_until timestamptz, next_attempt_at timestamptz NOT NULL DEFAULT now(),
        error_code varchar(40), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE(id,tenant_id), UNIQUE(tenant_id,dedupe_key),
        FOREIGN KEY(job_id,tenant_id) REFERENCES scan_jobs(id,tenant_id) ON DELETE RESTRICT,
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT,
        CHECK((kind='scan' AND job_id IS NOT NULL AND scan_id IS NULL AND target_id IS NULL AND target_fingerprint IS NULL)
           OR (kind='notification' AND scan_id IS NOT NULL AND target_id IS NOT NULL AND target_fingerprint IS NOT NULL))
    )''')
    op.execute('CREATE INDEX ix_delivery_due ON delivery_events(tenant_id,next_attempt_at,id) WHERE status IN (\'pending\',\'leased\',\'published\')')
    op.execute('CREATE INDEX ix_delivery_history ON delivery_events(tenant_id,created_at DESC,id DESC)')
    op.execute('''CREATE TABLE delivery_audit (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, event_id uuid NOT NULL,
        action varchar(32) NOT NULL, actor varchar(80) NOT NULL,
        status varchar(16) NOT NULL, attempts integer NOT NULL, error_code varchar(40),
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY(event_id,tenant_id) REFERENCES delivery_events(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('CREATE INDEX ix_delivery_audit_history ON delivery_audit(tenant_id,event_id,created_at,id)')
    op.execute('''CREATE TABLE delivery_dispatchers (
        tenant_id uuid PRIMARY KEY REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
        last_poll_at timestamptz NOT NULL, last_success_at timestamptz, last_error_at timestamptz
    )''')
    for table in ('delivery_events','delivery_audit','delivery_dispatchers'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"""CREATE POLICY tenant_isolation_{table} ON {table} FOR ALL
            USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)
            WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)""")
    op.execute('GRANT SELECT,INSERT,UPDATE ON delivery_events TO cloudsaver_app')
    op.execute('GRANT SELECT,INSERT ON delivery_audit TO cloudsaver_app')
    op.execute('GRANT SELECT,INSERT,UPDATE ON delivery_dispatchers TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.drop_table('delivery_dispatchers')
    op.drop_table('delivery_audit')
    op.drop_table('delivery_events')
    op.execute('ALTER TABLE scan_jobs DROP CONSTRAINT uq_scan_job_owner')
    # A non-superuser migration owner is otherwise subject to FORCE RLS and
    # cannot map queued states across tenants. The ACCESS EXCLUSIVE table lock
    # keeps runtime traffic out until FORCE is restored in this transaction.
    op.execute('ALTER TABLE scan_jobs NO FORCE ROW LEVEL SECURITY')
    op.execute("UPDATE scan_jobs SET notification_status='failed' WHERE notification_status='queued'")
    op.execute('ALTER TABLE scan_jobs FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE scan_jobs DROP CONSTRAINT ck_scan_jobs_notification')
    op.execute("ALTER TABLE scan_jobs ADD CONSTRAINT ck_scan_jobs_notification CHECK(notification_status IN ('not_requested','sent','failed'))")
