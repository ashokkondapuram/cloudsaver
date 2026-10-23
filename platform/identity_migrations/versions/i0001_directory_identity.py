"""token-db directory and identity schemas with least-privilege roles and forced RLS.

identity_app may read and write directory and key rows but can never delete them (scope lists excepted,
because they are replaced as a whole), can only insert and read key_events, and cannot reactivate a
deleted workspace or customer. identity_retention may only delete expired usage, failure and change rows.
Roles are created by the token-db init script; this migration only asserts they exist.
"""
revision = 'i0001_directory_identity'
down_revision = None
branch_labels = None
depends_on = None

SCOPE_TABLES = ('workspace_azure_subscriptions', 'workspace_aws_accounts', 'workspace_gcp_projects',
                'workspace_kubernetes_clusters')
ACTIONS = ('issued', 'rotated', 'rotated_out', 'revoked', 'revoked_all', 'expired', 'roles_changed',
           'providers_changed', 'expiry_changed', 'renamed', 'imported', 'hash_upgraded', 'customer_created',
           'customer_updated', 'workspace_created', 'workspace_updated', 'scopes_changed', 'workspace_suspended',
           'workspace_reactivated', 'workspace_deleted', 'platform_updated')
REASONS = ('malformed', 'unknown', 'secret_mismatch', 'revoked', 'expired', 'rotated_out', 'workspace_suspended',
           'throttled')


def values(items):
    return ','.join(f"'{item}'" for item in items)


def upgrade():
    from alembic import op
    op.execute('''DO $$ BEGIN
        IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('identity_app','identity_retention')) <> 2 THEN
            RAISE EXCEPTION 'Create identity_app and identity_retention before migrating token-db';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('identity_app','identity_retention')
                   AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb)) THEN
            RAISE EXCEPTION 'token-db runtime roles must be unprivileged';
        END IF;
    END $$''')
    op.execute('CREATE SCHEMA IF NOT EXISTS directory')
    op.execute('REVOKE ALL ON SCHEMA directory, identity FROM PUBLIC')
    op.execute('GRANT USAGE ON SCHEMA directory, identity TO identity_app, identity_retention')
    audit = ('created_at timestamptz NOT NULL DEFAULT now(), created_by varchar(120) NOT NULL, '
             'updated_at timestamptz NOT NULL DEFAULT now(), updated_by varchar(120) NOT NULL')
    op.execute(f'''CREATE TABLE directory.customers (
        id uuid PRIMARY KEY,
        name varchar(120) NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
        status varchar(16) NOT NULL CHECK (status IN ('active','suspended','deleted')),
        notes varchar(500),
        version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
        {audit},
        deleted_at timestamptz,
        CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
    )''')
    op.execute(f'''CREATE TABLE directory.workspaces (
        tenant_id uuid PRIMARY KEY,
        customer_id uuid NOT NULL REFERENCES directory.customers(id),
        name varchar(120) NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
        plan_tier varchar(16) NOT NULL CHECK (plan_tier IN ('STARTER','GROWTH','ENTERPRISE')),
        status varchar(16) NOT NULL CHECK (status IN ('active','suspended','deleted')),
        identity jsonb NOT NULL DEFAULT '{{}}' CHECK (jsonb_typeof(identity) = 'object' AND octet_length(identity::text) <= 2000),
        version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
        {audit},
        suspended_at timestamptz,
        deleted_at timestamptz,
        CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
    )''')
    op.execute('CREATE INDEX ix_workspaces_customer ON directory.workspaces(customer_id)')
    scope = ('tenant_id uuid NOT NULL REFERENCES directory.workspaces(tenant_id), position smallint NOT NULL, '
             'created_at timestamptz NOT NULL DEFAULT now(), created_by varchar(120) NOT NULL')
    op.execute(f'''CREATE TABLE directory.workspace_azure_subscriptions (
        {scope}, subscription_id uuid NOT NULL, PRIMARY KEY (tenant_id, subscription_id))''')
    op.execute(f'''CREATE TABLE directory.workspace_aws_accounts (
        {scope}, account_id char(12) NOT NULL CHECK (account_id ~ '^[0-9]{{12}}$'),
        region varchar(40) NOT NULL, role_arn varchar(600) NOT NULL, PRIMARY KEY (tenant_id, account_id, region))''')
    op.execute(f'''CREATE TABLE directory.workspace_gcp_projects (
        {scope}, project_id varchar(30) NOT NULL, regions text[] NOT NULL CHECK (cardinality(regions) BETWEEN 1 AND 50),
        PRIMARY KEY (tenant_id, project_id))''')
    op.execute(f'''CREATE TABLE directory.workspace_kubernetes_clusters (
        {scope}, cluster_id varchar(63) NOT NULL, prometheus_url varchar(2048) NOT NULL CHECK (prometheus_url LIKE 'https://%'),
        bearer_token_env varchar(120) NOT NULL CHECK (bearer_token_env ~ '^CLOUDSAVER_PROMETHEUS_TOKEN_[A-Z0-9_]{{1,80}}$'),
        PRIMARY KEY (tenant_id, cluster_id))''')
    op.execute('''CREATE TABLE directory.platform_settings (
        id smallint PRIMARY KEY CHECK (id = 1),
        scheduled_scans_enabled boolean NOT NULL, automated_alerts_enabled boolean NOT NULL,
        version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
        updated_by varchar(120) NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())''')
    op.execute("INSERT INTO directory.platform_settings VALUES (1, false, false, 1, 'bootstrap', now())")
    op.execute('''CREATE TABLE directory.directory_changes (
        seq bigserial PRIMARY KEY, tenant_id uuid,
        change_type varchar(32) NOT NULL CHECK (change_type IN ('workspace_upserted','workspace_deleted','platform_updated')),
        version integer NOT NULL, snapshot jsonb NOT NULL CHECK (octet_length(snapshot::text) <= 300000),
        occurred_at timestamptz NOT NULL DEFAULT now())''')
    op.execute('CREATE INDEX ix_directory_changes_occurred ON directory.directory_changes(occurred_at)')

    op.execute('''CREATE TABLE identity.api_keys (
        id uuid PRIMARY KEY,
        key_id varchar(12) NOT NULL UNIQUE CHECK (key_id ~ '^[0-9a-z]{12}$'),
        tenant_id uuid NOT NULL REFERENCES directory.workspaces(tenant_id),
        name varchar(80) NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
        roles text[] NOT NULL CHECK (cardinality(roles) >= 1 AND roles <@ ARRAY['TenantAdmin','BillingAdmin','Viewer']::text[]),
        all_providers boolean NOT NULL,
        allowed_providers text[] NOT NULL DEFAULT '{}' CHECK (allowed_providers <@ ARRAY['azure','aws','gcp','kubernetes']::text[]),
        scope_restrictions jsonb,
        format varchar(8) NOT NULL CHECK (format IN ('v1','legacy')),
        hash_scheme varchar(16) NOT NULL CHECK (hash_scheme IN ('hmac_sha256','sha256_legacy')),
        secret_digest bytea UNIQUE CHECK (secret_digest IS NULL OR octet_length(secret_digest) = 32),
        pepper_version smallint,
        legacy_sha256 char(64) UNIQUE CHECK (legacy_sha256 IS NULL OR legacy_sha256 ~ '^[0-9a-f]{64}$'),
        legacy_fingerprint bytea UNIQUE CHECK (legacy_fingerprint IS NULL OR octet_length(legacy_fingerprint) = 32),
        created_at timestamptz NOT NULL DEFAULT now(), created_by varchar(120) NOT NULL,
        expires_at timestamptz,
        revoked_at timestamptz, revoked_by varchar(120), revoke_reason varchar(200),
        rotated_from uuid REFERENCES identity.api_keys(id),
        rotates_out_at timestamptz,
        last_used_at timestamptz, last_used_ip inet,
        source varchar(16) NOT NULL CHECK (source IN ('portal','registry_import','env_import')),
        version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
        CHECK ((hash_scheme = 'hmac_sha256' AND secret_digest IS NOT NULL AND pepper_version IS NOT NULL AND legacy_sha256 IS NULL)
            OR (hash_scheme = 'sha256_legacy' AND legacy_sha256 IS NOT NULL AND secret_digest IS NULL)),
        CHECK (all_providers = (cardinality(allowed_providers) = 0)),
        CHECK (format = 'legacy' OR expires_at IS NOT NULL)
    )''')
    op.execute('CREATE INDEX ix_api_keys_tenant ON identity.api_keys(tenant_id, created_at DESC)')
    op.execute('''CREATE FUNCTION identity.guard_api_key() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.id <> OLD.id OR NEW.key_id <> OLD.key_id OR NEW.tenant_id <> OLD.tenant_id OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'Key identity is immutable' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION 'Revoked keys stay revoked' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER api_keys_guard BEFORE UPDATE ON identity.api_keys FOR EACH ROW EXECUTE FUNCTION identity.guard_api_key()')
    op.execute(f'''CREATE TABLE identity.key_events (
        id uuid PRIMARY KEY, occurred_at timestamptz NOT NULL DEFAULT now(),
        actor varchar(120) NOT NULL, actor_type varchar(16) NOT NULL CHECK (actor_type IN ('operator','service','system')),
        action varchar(40) NOT NULL CHECK (action IN ({values(ACTIONS)})),
        tenant_id uuid, key_id varchar(12), details jsonb NOT NULL DEFAULT '{{}}' CHECK (octet_length(details::text) <= 8000),
        request_id uuid)''')
    for name, columns in (('occurred', 'occurred_at DESC'), ('tenant', 'tenant_id, occurred_at DESC'),
                          ('key', 'key_id, occurred_at DESC')):
        op.execute(f'CREATE INDEX ix_key_events_{name} ON identity.key_events({columns})')
    op.execute('''CREATE FUNCTION identity.reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'key_events is append-only' USING ERRCODE = 'insufficient_privilege';
    END $$''')
    op.execute('CREATE TRIGGER key_events_append_only BEFORE UPDATE OR DELETE ON identity.key_events '
               'FOR EACH ROW EXECUTE FUNCTION identity.reject_change()')
    op.execute('CREATE TRIGGER key_events_no_truncate BEFORE TRUNCATE ON identity.key_events '
               'FOR EACH STATEMENT EXECUTE FUNCTION identity.reject_change()')
    op.execute('''CREATE TABLE identity.key_usage_hourly (
        key_id varchar(12) NOT NULL, hour timestamptz NOT NULL, source_ip inet NOT NULL,
        success_count integer NOT NULL DEFAULT 0 CHECK (success_count >= 0),
        failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
        last_seen_at timestamptz NOT NULL, PRIMARY KEY (key_id, hour, source_ip))''')
    op.execute(f'''CREATE TABLE identity.verification_failures_minute (
        minute timestamptz NOT NULL, source_ip inet NOT NULL, key_id varchar(12) NOT NULL DEFAULT '',
        tenant_id uuid, reason varchar(24) NOT NULL CHECK (reason IN ({values(REASONS)})),
        caller varchar(40) NOT NULL, count integer NOT NULL CHECK (count > 0),
        PRIMARY KEY (minute, source_ip, key_id, reason, caller))''')
    op.execute('CREATE INDEX ix_failures_minute ON identity.verification_failures_minute(minute DESC)')

    directory = ('directory.customers', 'directory.workspaces', 'directory.platform_settings')
    scopes = tuple('directory.' + t for t in SCOPE_TABLES)
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON {", ".join(directory)} TO identity_app')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {", ".join(scopes)} TO identity_app')
    op.execute('GRANT SELECT, INSERT ON directory.directory_changes, identity.key_events TO identity_app')
    op.execute('GRANT USAGE ON SEQUENCE directory.directory_changes_seq_seq TO identity_app')
    op.execute('GRANT SELECT, INSERT, UPDATE ON identity.api_keys, identity.key_usage_hourly, '
               'identity.verification_failures_minute TO identity_app')
    op.execute('GRANT SELECT, DELETE ON identity.key_usage_hourly, identity.verification_failures_minute, '
               'directory.directory_changes TO identity_retention')

    for table in directory + scopes + ('directory.directory_changes', 'identity.api_keys', 'identity.key_events',
                                       'identity.key_usage_hourly', 'identity.verification_failures_minute'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
    for table in ('directory.platform_settings', 'identity.api_keys', 'identity.key_usage_hourly',
                  'identity.verification_failures_minute') + scopes:
        op.execute(f'CREATE POLICY app_all ON {table} TO identity_app USING (true) WITH CHECK (true)')
    for table in ('directory.customers', 'directory.workspaces'):
        op.execute(f'CREATE POLICY app_read ON {table} FOR SELECT TO identity_app USING (true)')
        op.execute(f'CREATE POLICY app_insert ON {table} FOR INSERT TO identity_app WITH CHECK (true)')
        # Deleted directory rows are final; RLS hides them from UPDATE even if a bug tries.
        op.execute(f"CREATE POLICY app_update ON {table} FOR UPDATE TO identity_app USING (status <> 'deleted') WITH CHECK (true)")
    for table in ('directory.directory_changes', 'identity.key_events'):
        op.execute(f'CREATE POLICY app_read ON {table} FOR SELECT TO identity_app USING (true)')
        op.execute(f'CREATE POLICY app_insert ON {table} FOR INSERT TO identity_app WITH CHECK (true)')
    for table, column, days in (('identity.key_usage_hourly', 'hour', 90),
                                ('identity.verification_failures_minute', 'minute', 30),
                                ('directory.directory_changes', 'occurred_at', 30)):
        condition = f"{column} < now() - interval '{days} days'"
        op.execute(f'CREATE POLICY retention_read ON {table} FOR SELECT TO identity_retention USING ({condition})')
        op.execute(f'CREATE POLICY retention_delete ON {table} FOR DELETE TO identity_retention USING ({condition})')


def downgrade():
    from alembic import op
    op.execute('DROP SCHEMA directory CASCADE')
    for table in ('verification_failures_minute', 'key_usage_hourly', 'key_events', 'api_keys'):
        op.execute(f'DROP TABLE identity.{table} CASCADE')
    op.execute('DROP FUNCTION identity.reject_change()')
    op.execute('DROP FUNCTION identity.guard_api_key()')
