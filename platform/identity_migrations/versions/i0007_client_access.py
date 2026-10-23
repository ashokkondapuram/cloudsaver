"""Customer users, memberships, service accounts, and bootstrap keys."""
revision = 'i0007_client_access'
down_revision = 'i0006_analysis_knowledge'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute("ALTER TABLE directory.customers ADD COLUMN IF NOT EXISTS claim_status varchar(16) "
               "NOT NULL DEFAULT 'claimed' CHECK (claim_status IN ('pending','claimed'))")
    op.execute('ALTER TABLE directory.customers ADD COLUMN IF NOT EXISTS membership_policy_version '
               'integer NOT NULL DEFAULT 1 CHECK (membership_policy_version >= 1)')
    audit = ('created_at timestamptz NOT NULL DEFAULT now(), created_by varchar(120) NOT NULL, '
             'updated_at timestamptz NOT NULL DEFAULT now(), updated_by varchar(120) NOT NULL, '
             'version integer NOT NULL DEFAULT 1')
    op.execute(f'''CREATE TABLE identity.users (
        id uuid PRIMARY KEY,
        idp_issuer varchar(512) NOT NULL,
        idp_subject varchar(256) NOT NULL,
        email varchar(320),
        email_verified boolean NOT NULL DEFAULT false,
        display_name varchar(120) NOT NULL,
        status varchar(16) NOT NULL CHECK (status IN ('active','suspended','deleted')),
        last_sign_in_at timestamptz,
        {audit},
        UNIQUE (idp_issuer, idp_subject))''')
    op.execute(f'''CREATE TABLE identity.customer_memberships (
        customer_id uuid NOT NULL REFERENCES directory.customers(id),
        user_id uuid NOT NULL REFERENCES identity.users(id),
        role varchar(24) NOT NULL CHECK (role IN ('CustomerOwner','CustomerAdmin','CustomerAuditor')),
        status varchar(16) NOT NULL CHECK (status IN ('active','suspended')),
        {audit},
        PRIMARY KEY (customer_id, user_id))''')
    op.execute('CREATE UNIQUE INDEX ux_customer_owner ON identity.customer_memberships(customer_id) '
               "WHERE role = 'CustomerOwner' AND status = 'active'")
    op.execute(f'''CREATE TABLE identity.workspace_memberships (
        tenant_id uuid NOT NULL REFERENCES directory.workspaces(tenant_id),
        user_id uuid NOT NULL REFERENCES identity.users(id),
        roles text[] NOT NULL CHECK (cardinality(roles) >= 1 AND roles <@ ARRAY['TenantAdmin','BillingAdmin','Viewer']::text[]),
        {audit},
        PRIMARY KEY (tenant_id, user_id))''')
    op.execute(f'''CREATE TABLE identity.service_accounts (
        id uuid PRIMARY KEY,
        customer_id uuid NOT NULL REFERENCES directory.customers(id),
        name varchar(80) NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
        description varchar(500) NOT NULL DEFAULT '',
        status varchar(16) NOT NULL CHECK (status IN ('active','suspended','deleted')),
        {audit})''')
    op.execute("ALTER TABLE identity.api_keys ADD COLUMN IF NOT EXISTS purpose varchar(16) "
               "NOT NULL DEFAULT 'standard' CHECK (purpose IN ('standard','bootstrap'))")
    op.execute("ALTER TABLE identity.api_keys ADD COLUMN IF NOT EXISTS subject_type varchar(16) "
               "NOT NULL DEFAULT 'operator' CHECK (subject_type IN ('operator','user','service_account'))")
    op.execute('ALTER TABLE identity.api_keys ADD COLUMN IF NOT EXISTS subject_user_id uuid '
               'REFERENCES identity.users(id)')
    op.execute('ALTER TABLE identity.api_keys ADD COLUMN IF NOT EXISTS service_account_id uuid '
               'REFERENCES identity.service_accounts(id)')
    op.execute('ALTER TABLE identity.api_keys ADD COLUMN IF NOT EXISTS claimed_at timestamptz')
    for table in ('identity.users', 'identity.customer_memberships', 'identity.workspace_memberships',
                  'identity.service_accounts'):
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON {table} TO identity_app')
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY app_all ON {table} TO identity_app USING (true) WITH CHECK (true)')
    op.execute('GRANT DELETE ON identity.workspace_memberships TO identity_app')
    # Billing, analysis, knowledge, and customer modules each add actions; enforce shape, not an allowlist.
    op.execute('ALTER TABLE identity.key_events DROP CONSTRAINT IF EXISTS key_events_action_check')
    op.execute("ALTER TABLE identity.key_events ADD CONSTRAINT key_events_action_check "
               "CHECK (action ~ '^[a-z][a-z_]{1,39}$')")
    op.execute('ALTER TABLE identity.key_events DROP CONSTRAINT IF EXISTS key_events_actor_type_check')
    op.execute("ALTER TABLE identity.key_events ADD CONSTRAINT key_events_actor_type_check "
               "CHECK (actor_type IN ('operator','service','system','customer'))")


def downgrade():
    from alembic import op
    op.execute('ALTER TABLE identity.api_keys DROP COLUMN IF EXISTS claimed_at')
    op.execute('ALTER TABLE identity.api_keys DROP COLUMN IF EXISTS service_account_id')
    op.execute('ALTER TABLE identity.api_keys DROP COLUMN IF EXISTS subject_user_id')
    op.execute('ALTER TABLE identity.api_keys DROP COLUMN IF EXISTS subject_type')
    op.execute('ALTER TABLE identity.api_keys DROP COLUMN IF EXISTS purpose')
    op.execute('DROP TABLE IF EXISTS identity.service_accounts')
    op.execute('DROP TABLE IF EXISTS identity.workspace_memberships')
    op.execute('DROP TABLE IF EXISTS identity.customer_memberships')
    op.execute('DROP TABLE IF EXISTS identity.users')
    op.execute('ALTER TABLE directory.customers DROP COLUMN IF EXISTS membership_policy_version')
    op.execute('ALTER TABLE directory.customers DROP COLUMN IF EXISTS claim_status')
