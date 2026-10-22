"""Run migrations as a schema owner, never through the application role."""
import os

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import make_url

from database.models import Base

target_metadata = Base.metadata
raw_url = os.environ.get('CLOUDSAVER_MIGRATION_URL')
if not raw_url:
    raise RuntimeError('Set CLOUDSAVER_MIGRATION_URL to a schema-owner PostgreSQL DSN')
url = make_url(raw_url)
if url.get_backend_name() != 'postgresql':
    raise RuntimeError('Domain migrations require PostgreSQL')
if url.username == 'cloudsaver_app':
    raise RuntimeError('Application role cannot run schema migrations')
url = url.set(drivername='postgresql+psycopg')

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        if connection.scalar(text('SELECT current_user')) == 'cloudsaver_app':
            raise RuntimeError('Application role cannot run schema migrations')
        connection.rollback()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
