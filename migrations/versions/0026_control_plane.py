"""Control-plane pilot: financial scenarios, action assessments, versioned plans, approvals, GitOps checks."""
revision = '0026_control_plane'
down_revision = '0025_observability_connectors'
branch_labels = depends_on = None

TABLES = {
    'cp_financial_scenarios': ("""CREATE TABLE cp_financial_scenarios (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,idempotency_key text NOT NULL,currency char(3) NOT NULL,
        input jsonb NOT NULL,result jsonb NOT NULL,status varchar(20) NOT NULL,evidence_digest char(64),
        created_by_hash char(64) NOT NULL,created_at timestamptz NOT NULL,UNIQUE(tenant_id,idempotency_key))""", 'SELECT,INSERT'),
    'cp_action_assessments': ("""CREATE TABLE cp_action_assessments (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,idempotency_key text NOT NULL,action_id text NOT NULL,
        rule_version varchar(16) NOT NULL,findings jsonb NOT NULL,decision varchar(24) NOT NULL,
        evidence_digest char(64) NOT NULL,policy_digest char(64) NOT NULL,created_by_hash char(64) NOT NULL,
        created_at timestamptz NOT NULL,UNIQUE(tenant_id,idempotency_key),
        CHECK (decision IN ('eligible_for_review','blocked','evidence_required','unsupported','expired')))""", 'SELECT,INSERT'),
    'cp_plans': ("""CREATE TABLE cp_plans (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,objective text NOT NULL,owner_hash char(64) NOT NULL,
        created_at timestamptz NOT NULL,UNIQUE(tenant_id,id))""", 'SELECT,INSERT'),
    'cp_plan_versions': ("""CREATE TABLE cp_plan_versions (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,plan_id uuid NOT NULL,version integer NOT NULL CHECK (version>=1),
        identity_digest char(64) NOT NULL,targets jsonb NOT NULL,parameters jsonb NOT NULL,
        policy_digest char(64) NOT NULL,evidence_digest char(64) NOT NULL,state varchar(32) NOT NULL DEFAULT 'draft',
        created_by_hash char(64) NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
        UNIQUE(tenant_id,plan_id,version),UNIQUE(tenant_id,id),
        FOREIGN KEY (tenant_id,plan_id) REFERENCES cp_plans(tenant_id,id),
        CHECK (state IN ('draft','evidence_required','assessed','review_requested','approved','queued','running',
          'verification_pending','verified','failed','reconciliation_required','cancelled','expired')))""", 'SELECT,INSERT'),
    'cp_plan_approvals': ("""CREATE TABLE cp_plan_approvals (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,plan_version_id uuid NOT NULL,identity_digest char(64) NOT NULL,
        approver_hash char(64) NOT NULL,verified_human boolean NOT NULL,expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL,
        FOREIGN KEY (tenant_id,plan_version_id) REFERENCES cp_plan_versions(tenant_id,id))""", 'SELECT,INSERT'),
    'cp_gitops_deliveries': ("""CREATE TABLE cp_gitops_deliveries (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,delivery_id text NOT NULL,repo_id bigint NOT NULL,
        received_at timestamptz NOT NULL,UNIQUE(tenant_id,delivery_id))""", 'SELECT,INSERT'),
    'cp_gitops_checks': ("""CREATE TABLE cp_gitops_checks (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,repo_id bigint NOT NULL,base_sha varchar(64) NOT NULL,
        head_sha varchar(64) NOT NULL,plan_digest char(64) NOT NULL,policy_digest char(64) NOT NULL,
        evidence_digest char(64) NOT NULL,decision varchar(24) NOT NULL,trusted_plan boolean NOT NULL,
        conclusion varchar(16) NOT NULL,created_at timestamptz NOT NULL,
        UNIQUE(tenant_id,repo_id,base_sha,head_sha,plan_digest,policy_digest,evidence_digest))""", 'SELECT,INSERT'),
    'cp_commitment_reminders': ("""CREATE TABLE cp_commitment_reminders (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,commitment_id text NOT NULL,threshold_days integer NOT NULL,
        days_remaining integer NOT NULL,created_at timestamptz NOT NULL,
        UNIQUE(tenant_id,commitment_id,threshold_days))""", 'SELECT,INSERT'),
}


def upgrade():
    from alembic import op
    owner = "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
    for table, (ddl, grants) in TABLES.items():
        op.execute(ddl)
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({owner}) WITH CHECK ({owner})')
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT {grants} ON {table} TO cloudsaver_app')
    # Only lifecycle state may change on a plan version; all other columns stay immutable.
    op.execute('GRANT UPDATE (state, updated_at) ON cp_plan_versions TO cloudsaver_app')
    op.execute('CREATE INDEX cp_action_assessments_action ON cp_action_assessments(tenant_id,action_id,created_at DESC)')
    op.execute('CREATE INDEX cp_plan_versions_state ON cp_plan_versions(tenant_id,state,created_at)')
    op.execute('CREATE INDEX cp_gitops_checks_head ON cp_gitops_checks(tenant_id,repo_id,head_sha)')


def downgrade():
    from alembic import op
    for table in reversed(list(TABLES)):
        op.execute(f'DROP TABLE {table}')
