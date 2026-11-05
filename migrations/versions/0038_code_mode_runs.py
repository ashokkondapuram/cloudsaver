"""Cloudflare Code Mode durable run history."""
revision = '0038_code_mode_runs'
down_revision = '0037_scans_update_delete_grants'
branch_labels = depends_on = None


def upgrade():
    from alembic import op

    op.execute(
        '''CREATE TABLE code_mode_runs (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL,
            request_key uuid NOT NULL,
            fingerprint char(64) NOT NULL,
            state varchar(32) NOT NULL,
            version integer NOT NULL CHECK(version>0),
            snippet_digest char(64) NOT NULL,
            payload jsonb NOT NULL,
            result jsonb,
            actor varchar(128) NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            UNIQUE(tenant_id, request_key),
            UNIQUE(id, tenant_id),
            CHECK(octet_length(payload::text)<=20000))'''
    )
    op.execute(
        '''CREATE TABLE code_mode_run_events (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL,
            run_id uuid NOT NULL,
            version integer NOT NULL,
            action varchar(60) NOT NULL,
            actor varchar(128) NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            UNIQUE(run_id, version),
            CHECK(octet_length(payload::text)<=20000),
            FOREIGN KEY(run_id, tenant_id) REFERENCES code_mode_runs(id, tenant_id) ON DELETE RESTRICT)'''
    )
    for table in ('code_mode_runs', 'code_mode_run_events'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid) "
            f"WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)"
        )
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT SELECT,INSERT ON {table} TO cloudsaver_app')
    op.execute('GRANT UPDATE(state,version,result,updated_at) ON code_mode_runs TO cloudsaver_app')


def downgrade():
    from alembic import op

    op.execute('DROP TABLE code_mode_run_events')
    op.execute('DROP TABLE code_mode_runs')
