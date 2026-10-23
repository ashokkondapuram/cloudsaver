"""Analysis rule catalog, workspace rule settings, and shared knowledge publications."""
revision = 'i0006_analysis_knowledge'
down_revision = 'i0005_plan_change_pending_unique'
branch_labels = None
depends_on = None

RULE_SEED = (
    ('ORPHANED_DISK', 'azure', 'storage', 'microsoft.compute/disks', 'Unattached managed disk', 'cost'),
    ('UNASSOCIATED_PUBLIC_IP', 'azure', 'network', 'microsoft.network/publicipaddresses', 'Unassociated public IP', 'cost'),
    ('STOPPED_VM', 'azure', 'compute', 'microsoft.compute/virtualmachines', 'Stopped virtual machine', 'cost'),
    ('EMPTY_APP_SERVICE_PLAN', 'azure', 'application', 'microsoft.web/serverfarms', 'Empty App Service plan', 'cost'),
    ('ORPHANED_NIC', 'azure', 'network', 'microsoft.network/networkinterfaces', 'Unattached network interface', 'cost'),
    ('ORPHANED_NSG', 'azure', 'network', 'microsoft.network/networksecuritygroups', 'Unassociated network security group', 'cost'),
    ('IDLE_APP_GATEWAY', 'azure', 'network', 'microsoft.network/applicationgateways', 'Stopped or empty Application Gateway', 'cost'),
    ('AWS_UNATTACHED_EBS', 'aws', 'storage', 'ebs', 'Unattached EBS volume', 'cost'),
    ('AWS_UNASSOCIATED_EIP', 'aws', 'network', 'elastic-ip', 'Unassociated Elastic IP', 'cost'),
    ('AWS_IDLE_RDS', 'aws', 'database', 'rds', 'Stopped RDS instance', 'cost'),
    ('GCP_UNATTACHED_DISK', 'gcp', 'storage', 'disk', 'Unattached persistent disk', 'cost'),
    ('GCP_UNASSIGNED_ADDRESS', 'gcp', 'network', 'address', 'Unassigned static IP', 'cost'),
    ('GCP_IDLE_CLOUD_SQL', 'gcp', 'database', 'cloud-sql', 'Idle Cloud SQL instance', 'cost'),
    ('K8S_CPU_OVERSIZED', 'kubernetes', 'compute', 'pod', 'Oversized CPU requests', 'performance'),
    ('K8S_MEMORY_OVERSIZED', 'kubernetes', 'compute', 'pod', 'Oversized memory requests', 'performance'),
)


def upgrade():
    from alembic import op
    op.execute('CREATE SCHEMA IF NOT EXISTS analysis')
    op.execute('CREATE SCHEMA IF NOT EXISTS knowledge')
    op.execute('REVOKE ALL ON SCHEMA analysis, knowledge FROM PUBLIC')
    op.execute('GRANT USAGE ON SCHEMA analysis, knowledge TO identity_app, identity_retention')
    audit = ('created_at timestamptz NOT NULL DEFAULT now(), created_by varchar(120) NOT NULL, '
             'updated_at timestamptz NOT NULL DEFAULT now(), updated_by varchar(120) NOT NULL, version integer NOT NULL DEFAULT 1')
    op.execute(f'''CREATE TABLE analysis.rule_catalog (
        id varchar(80) PRIMARY KEY,
        provider varchar(16) NOT NULL,
        service_category varchar(24) NOT NULL,
        resource_type varchar(128) NOT NULL,
        name varchar(200) NOT NULL,
        description varchar(2000) NOT NULL DEFAULT '',
        pillar varchar(24) NOT NULL,
        status varchar(16) NOT NULL CHECK (status IN ('published','retired')),
        {audit})''')
    op.execute(f'''CREATE TABLE analysis.workspace_rules (
        tenant_id uuid NOT NULL REFERENCES directory.workspaces(tenant_id),
        rule_id varchar(80) NOT NULL REFERENCES analysis.rule_catalog(id),
        enabled boolean NOT NULL DEFAULT true,
        unavailable_reason varchar(500),
        {audit},
        PRIMARY KEY (tenant_id, rule_id))''')
    op.execute(f'''CREATE TABLE knowledge.publications (
        id uuid PRIMARY KEY,
        title varchar(200) NOT NULL,
        summary varchar(2000) NOT NULL,
        body varchar(8000) NOT NULL,
        status varchar(16) NOT NULL CHECK (status IN ('draft','published','deprecated','rejected')),
        quality_score smallint CHECK (quality_score IS NULL OR quality_score BETWEEN 0 AND 100),
        {audit})''')
    for rule_id, provider, category, rtype, name, pillar in RULE_SEED:
        safe = name.replace("'", "''")
        op.execute(
            f"INSERT INTO analysis.rule_catalog (id, provider, service_category, resource_type, name, description, pillar, "
            f"status, created_by, updated_by) VALUES ('{rule_id}', '{provider}', '{category}', '{rtype}', '{safe}', '', "
            f"'{pillar}', 'published', 'bootstrap', 'bootstrap')"
        )
    for table in ('analysis.rule_catalog', 'analysis.workspace_rules', 'knowledge.publications'):
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON {table} TO identity_app')
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY app_all ON {table} TO identity_app USING (true) WITH CHECK (true)')


def downgrade():
    from alembic import op
    op.execute('DROP SCHEMA IF EXISTS knowledge CASCADE')
    op.execute('DROP SCHEMA IF EXISTS analysis CASCADE')
