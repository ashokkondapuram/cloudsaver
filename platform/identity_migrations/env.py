"""platform-db migrations run as identity_owner, never as the identity_app runtime role."""
from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import make_url

from identity.config import env

raw_url = env('IDENTITY_MIGRATION_URL')
if not raw_url:
    raise RuntimeError('Set PLATFORM_IDENTITY_MIGRATION_URL to the platform-db owner DSN')
url = make_url(raw_url)
if url.get_backend_name() != 'postgresql':
    raise RuntimeError('token-db migrations require PostgreSQL')
if url.username in ('identity_app', 'identity_retention'):
    raise RuntimeError('Runtime roles cannot run schema migrations')
url = url.set(drivername='postgresql+psycopg')

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    if connection.scalar(text('SELECT current_user')) in ('identity_app', 'identity_retention'):
        raise RuntimeError('Runtime roles cannot run schema migrations')
    connection.execute(text('CREATE SCHEMA IF NOT EXISTS identity'))
    connection.commit()
    context.configure(connection=connection, target_metadata=None, version_table='alembic_version',
                      version_table_schema='identity')
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
