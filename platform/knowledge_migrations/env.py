"""Dedicated knowledge database owner migrations; never use the identity database."""
from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import make_url
from identity.config import env
from identity.knowledge.store import PostgresKnowledgeStore

raw = env('KNOWLEDGE_MIGRATION_URL')
if not raw:
    raise RuntimeError('Set PLATFORM_KNOWLEDGE_MIGRATION_URL')
PostgresKnowledgeStore(raw, env('IDENTITY_MIGRATION_URL'))
engine = create_engine(make_url(raw).set(drivername='postgresql+psycopg'), poolclass=pool.NullPool)
with engine.connect() as connection:
    if connection.scalar(text('SELECT current_user')) == 'knowledge_app':
        raise RuntimeError('Knowledge migrations require an owner role')
    connection.commit()
    context.configure(connection=connection, version_table='knowledge_alembic_version')
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
