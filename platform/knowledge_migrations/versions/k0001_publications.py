"""Only public/synthetic reviewed knowledge; no references to client data."""
revision = 'k0001_publications'
down_revision = branch_labels = depends_on = None


def upgrade():
    from alembic import op
    op.execute('CREATE SCHEMA knowledge')
    op.execute('REVOKE ALL ON SCHEMA knowledge FROM PUBLIC')
    op.execute('GRANT USAGE ON SCHEMA knowledge TO knowledge_app')
    op.execute('''CREATE TABLE knowledge.publications (
        id uuid PRIMARY KEY, title varchar(200) NOT NULL, summary varchar(2000) NOT NULL,
        body varchar(8000) NOT NULL, status varchar(16) NOT NULL CHECK(status IN ('draft','published','deprecated','rejected')),
        quality_score smallint CHECK(quality_score BETWEEN 0 AND 100),
        source_kind varchar(32) NOT NULL CHECK(source_kind IN ('synthetic','public_documentation')),
        source_url text, applicability jsonb NOT NULL DEFAULT '{}', reviews jsonb NOT NULL DEFAULT '{}',
        created_at timestamptz NOT NULL, created_by varchar(120) NOT NULL,
        updated_at timestamptz NOT NULL, updated_by varchar(120) NOT NULL, version integer NOT NULL DEFAULT 1)''')
    op.execute('''CREATE TABLE knowledge.audit(id uuid PRIMARY KEY,occurred_at timestamptz NOT NULL,
        actor varchar(120) NOT NULL,action varchar(80) NOT NULL,details jsonb NOT NULL)''')
    op.execute('GRANT SELECT,INSERT,UPDATE ON knowledge.publications TO knowledge_app')
    op.execute('GRANT SELECT,INSERT ON knowledge.audit TO knowledge_app')
    for table in ('publications', 'audit'):
        op.execute(f'ALTER TABLE knowledge.{table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY knowledge_service ON knowledge.{table} TO knowledge_app USING(true) WITH CHECK(true)')


def downgrade():
    from alembic import op
    op.execute('DROP SCHEMA knowledge CASCADE')
