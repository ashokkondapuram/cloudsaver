"""Versioned, operator-owned global AI ceilings and kill switches."""
revision = 'i0011_ai_foundry_policy'
down_revision = 'i0010_analysis_policy'
branch_labels = depends_on = None


def upgrade():
    from alembic import op
    from identity.ai_policy import DEFAULT_POLICY
    import json
    import sqlalchemy as sa
    # Only fill the new entitlement; preserve explicit custom plan choices and all other limits.
    op.execute("ALTER TABLE billing.plans NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE billing.plans SET entitlements=entitlements || jsonb_build_object('can_use_ai_advisory',code IN ('GROWTH','ENTERPRISE')), version=version+1, updated_at=now(), updated_by='ai-foundry-migration' WHERE NOT entitlements ? 'can_use_ai_advisory'")
    op.execute("ALTER TABLE billing.plans FORCE ROW LEVEL SECURITY")
    op.execute('''CREATE TABLE directory.ai_foundry_policy (
        id smallint PRIMARY KEY CHECK(id=1), policy jsonb NOT NULL CHECK(octet_length(policy::text)<=64000),
        version integer NOT NULL DEFAULT 1 CHECK(version>=1), updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by varchar(120) NOT NULL)''')
    op.get_bind().execute(sa.text("INSERT INTO directory.ai_foundry_policy(id,policy,updated_by) VALUES(1,CAST(:policy AS jsonb),'migration')"),
                          {'policy': json.dumps(DEFAULT_POLICY)})
    op.execute('REVOKE ALL ON directory.ai_foundry_policy FROM PUBLIC')
    op.execute('GRANT SELECT,UPDATE ON directory.ai_foundry_policy TO identity_app')
    op.execute('ALTER TABLE directory.ai_foundry_policy ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE directory.ai_foundry_policy FORCE ROW LEVEL SECURITY')
    op.execute('CREATE POLICY ai_control_plane ON directory.ai_foundry_policy TO identity_app USING(true) WITH CHECK(true)')


def downgrade():
    from alembic import op
    op.execute('DROP TABLE directory.ai_foundry_policy')
