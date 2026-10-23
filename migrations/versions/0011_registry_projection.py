"""Tenant registry becomes a projection of the platform directory.

After cutover the tenant-service projector is the only writer of directory-owned
columns. Key digests move to token-db, so api_key_sha256 becomes nullable and is
dropped in 0012. The export role exists only for the one-time identity import.
"""
import os

revision = '0011_registry_projection'
down_revision = '0010_resource_assessment'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    op.execute('ALTER TABLE tenant_registry ALTER COLUMN api_key_sha256 DROP NOT NULL')
    op.execute('ALTER TABLE tenant_registry ADD COLUMN customer_id uuid, ADD COLUMN directory_version integer '
               'CHECK(directory_version IS NULL OR directory_version >= 1), ADD COLUMN projected_at timestamptz')
    op.execute('''CREATE TABLE directory_projection_cursor (
        id smallint PRIMARY KEY CHECK(id = 1),
        seq bigint NOT NULL CHECK(seq >= 0),
        updated_at timestamptz NOT NULL DEFAULT now()
    )''')
    op.execute('GRANT SELECT,INSERT,UPDATE ON directory_projection_cursor TO cloudsaver_app')
    bind = op.get_bind()
    password = os.getenv('CLOUDSAVER_REGISTRY_EXPORT_PASSWORD', '')
    exists = bind.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname='cloudsaver_registry_export'").scalar()
    can_create = bind.exec_driver_sql('SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user').scalar()
    if not exists and not can_create:
        # Least-privilege migration owners can't create roles; the import job is then unavailable.
        return
    if not exists:
        op.execute('CREATE ROLE cloudsaver_registry_export NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE')
    if password and can_create:
        quoted = op.get_bind().exec_driver_sql('SELECT quote_literal(%(p)s)', {'p': password}).scalar()
        op.execute(f'ALTER ROLE cloudsaver_registry_export LOGIN PASSWORD {quoted}')
    database = op.get_bind().exec_driver_sql('SELECT quote_ident(current_database())').scalar()
    op.execute(f'GRANT CONNECT ON DATABASE {database} TO cloudsaver_registry_export')
    op.execute('GRANT USAGE ON SCHEMA public TO cloudsaver_registry_export')
    op.execute('GRANT SELECT ON tenant_registry, platform_settings TO cloudsaver_registry_export')


def downgrade():
    from alembic import op
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname='cloudsaver_registry_export'").scalar():
        op.execute('REVOKE ALL ON tenant_registry, platform_settings FROM cloudsaver_registry_export')
        op.execute('REVOKE USAGE ON SCHEMA public FROM cloudsaver_registry_export')
        database = bind.exec_driver_sql('SELECT quote_ident(current_database())').scalar()
        op.execute(f'REVOKE CONNECT ON DATABASE {database} FROM cloudsaver_registry_export')
        if bind.exec_driver_sql('SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user').scalar():
            op.execute('DROP ROLE cloudsaver_registry_export')
    op.drop_table('directory_projection_cursor')
    op.execute('ALTER TABLE tenant_registry DROP COLUMN projected_at, DROP COLUMN directory_version, DROP COLUMN customer_id')
    op.execute("DELETE FROM tenant_registry WHERE api_key_sha256 IS NULL")
    op.execute('ALTER TABLE tenant_registry ALTER COLUMN api_key_sha256 SET NOT NULL')
