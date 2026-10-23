"""Durable inference evidence and tenant-owned normalized billing imports."""
revision = '0009_enterprise_evidence'
down_revision = '0008_tenant_registry'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE ai_inference_attempts (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, request_key uuid NOT NULL,
        fingerprint char(64) NOT NULL, scan_id uuid NOT NULL,
        metadata jsonb NOT NULL CHECK(octet_length(metadata::text)<=8000),
        status varchar(16) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','uncertain')),
        response jsonb CHECK(response IS NULL OR octet_length(response::text)<=64000),
        input_tokens bigint CHECK(input_tokens BETWEEN 0 AND 10000000),
        output_tokens bigint CHECK(output_tokens BETWEEN 0 AND 10000000),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz,
        UNIQUE(tenant_id,request_key), UNIQUE(id,tenant_id),
        FOREIGN KEY(scan_id,tenant_id) REFERENCES scans(id,tenant_id) ON DELETE RESTRICT,
        CHECK((status='completed' AND response IS NOT NULL AND completed_at IS NOT NULL)
            OR (status<>'completed' AND response IS NULL AND completed_at IS NULL))
    )''')
    op.execute('CREATE INDEX ix_ai_attempt_history ON ai_inference_attempts(tenant_id,created_at DESC,id DESC)')
    op.execute('''CREATE TABLE ai_inference_events (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, attempt_id uuid NOT NULL,
        action varchar(16) NOT NULL CHECK(action IN ('claimed','completed','uncertain')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        FOREIGN KEY(attempt_id,tenant_id) REFERENCES ai_inference_attempts(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('''CREATE TABLE focus_imports (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, source_id varchar(100) NOT NULL,
        fingerprint char(64) NOT NULL, provider varchar(8) NOT NULL CHECK(provider IN ('azure','aws','gcp')),
        sub_account varchar(128) NOT NULL, currency char(3) NOT NULL,
        period_start date NOT NULL, period_end date NOT NULL, complete boolean NOT NULL,
        records integer NOT NULL CHECK(records BETWEEN 0 AND 5000), inserted integer NOT NULL CHECK(inserted BETWEEN 0 AND 5000),
        actor char(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK(period_end>period_start AND period_end-period_start<=366),
        UNIQUE(tenant_id,source_id), UNIQUE(id,tenant_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('''CREATE TABLE focus_charges (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, import_id uuid NOT NULL,
        provider varchar(8) NOT NULL, billing_account varchar(128) NOT NULL, sub_account varchar(128) NOT NULL,
        charge_id varchar(128) NOT NULL, fingerprint char(64) NOT NULL, currency char(3) NOT NULL,
        period_start timestamptz NOT NULL, period_end timestamptz NOT NULL, resource_id text,
        charge_category varchar(16) NOT NULL, billed_cost numeric(24,8) NOT NULL,
        effective_cost numeric(24,8) NOT NULL, list_cost numeric(24,8),
        CHECK(period_end>period_start AND period_end-period_start<=interval '366 days'),
        UNIQUE(tenant_id,provider,billing_account,charge_id),
        FOREIGN KEY(import_id,tenant_id) REFERENCES focus_imports(id,tenant_id) ON DELETE RESTRICT
    )''')
    op.execute('CREATE INDEX ix_focus_charge_period ON focus_charges(tenant_id,currency,period_start,period_end)')
    op.execute('CREATE INDEX ix_focus_import_period ON focus_imports(tenant_id,provider,sub_account,currency,period_start,period_end)')
    for table in ('ai_inference_attempts','ai_inference_events','focus_imports','focus_charges'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"""CREATE POLICY tenant_isolation_{table} ON {table} FOR ALL
            USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)
            WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)""")
        op.execute(f'GRANT SELECT,INSERT ON {table} TO cloudsaver_app')
    op.execute('GRANT UPDATE(status,response,input_tokens,output_tokens,completed_at) ON ai_inference_attempts TO cloudsaver_app')
    op.execute('''CREATE FUNCTION protect_inference_outcome() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status <> 'pending' OR NEW.status NOT IN ('completed','uncertain') THEN
            RAISE EXCEPTION 'Inference outcomes are final' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$''')
    op.execute('CREATE TRIGGER immutable_inference_outcome BEFORE UPDATE ON ai_inference_attempts FOR EACH ROW EXECUTE FUNCTION protect_inference_outcome()')


def downgrade():
    from alembic import op
    for table in ('focus_charges','focus_imports','ai_inference_events','ai_inference_attempts'):
        op.drop_table(table)
    op.execute('DROP FUNCTION protect_inference_outcome()')
