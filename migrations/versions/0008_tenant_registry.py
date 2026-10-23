"""Runtime tenant registry, platform settings and settings audit.

tenant_registry is the authentication directory: it is read across tenants to
match access keys, so it deliberately has no row-level security and stores no
secret material other than the write-only notification webhook.
"""
revision = '0008_tenant_registry'
down_revision = '0007_delivery_outbox'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('''CREATE TABLE tenant_registry (
        tenant_id uuid PRIMARY KEY,
        name varchar(120) NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
        plan_tier varchar(16) NOT NULL CHECK(plan_tier IN ('STARTER','GROWTH','ENTERPRISE')),
        api_key_sha256 char(64) NOT NULL UNIQUE CHECK(api_key_sha256 ~ '^[0-9a-f]{64}$'),
        active boolean NOT NULL DEFAULT true,
        config jsonb NOT NULL DEFAULT '{}' CHECK(octet_length(config::text) <= 200000),
        webhook_url text CHECK(webhook_url IS NULL OR length(webhook_url) <= 4096),
        version integer NOT NULL DEFAULT 1 CHECK(version >= 1),
        updated_by varchar(80) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )''')
    op.execute('''CREATE TABLE platform_settings (
        id smallint PRIMARY KEY CHECK(id = 1),
        settings jsonb NOT NULL CHECK(octet_length(settings::text) <= 16000),
        version integer NOT NULL DEFAULT 1 CHECK(version >= 1),
        updated_by varchar(80) NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    )''')
    op.execute('''CREATE TABLE settings_audit (
        id uuid PRIMARY KEY, tenant_id uuid, actor varchar(80) NOT NULL,
        action varchar(40) NOT NULL, version integer NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )''')
    op.execute('CREATE INDEX ix_settings_audit_tenant ON settings_audit(tenant_id, created_at DESC)')
    op.execute('GRANT SELECT,INSERT,UPDATE ON tenant_registry TO cloudsaver_app')
    op.execute('GRANT SELECT,INSERT,UPDATE ON platform_settings TO cloudsaver_app')
    op.execute('GRANT SELECT,INSERT ON settings_audit TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.drop_table('settings_audit')
    op.drop_table('platform_settings')
    op.drop_table('tenant_registry')
