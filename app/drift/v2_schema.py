"""v2.0 drift baselines, drift event log, and GitOps AST tables (migration 0029)."""

TABLES = {
    "resource_state_baselines": """CREATE TABLE resource_state_baselines (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        canonical_resource_id text NOT NULL,
        provider varchar(20) NOT NULL,
        baseline_hash char(64) NOT NULL,
        expected_state jsonb NOT NULL,
        captured_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id),
        UNIQUE(tenant_id,canonical_resource_id)
    )""",
    "cloud_drift_events": """CREATE TABLE cloud_drift_events (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        canonical_resource_id text NOT NULL,
        provider varchar(20) NOT NULL,
        operation varchar(120) NOT NULL,
        actor_principal text NOT NULL,
        baseline_hash char(64),
        live_hash char(64),
        drifted_fields jsonb NOT NULL,
        permit_action varchar(40),
        ai_classification jsonb,
        detected_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id)
    )""",
    "gitops_repositories": """CREATE TABLE gitops_repositories (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        repo_url text NOT NULL,
        default_branch varchar(120) NOT NULL,
        vcs_provider varchar(20) NOT NULL DEFAULT 'github',
        external_binding jsonb NOT NULL,
        last_synced_at timestamptz,
        PRIMARY KEY(tenant_id,id),
        UNIQUE(tenant_id,repo_url)
    )""",
    "gitops_ast_files": """CREATE TABLE gitops_ast_files (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        repository_id uuid NOT NULL,
        file_path text NOT NULL,
        commit_sha char(40) NOT NULL,
        manifest_format varchar(20) NOT NULL,
        parsed_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id),
        UNIQUE(tenant_id,repository_id,file_path,commit_sha),
        FOREIGN KEY(tenant_id,repository_id) REFERENCES gitops_repositories(tenant_id,id)
    )""",
    "gitops_ast_resource_mappings": """CREATE TABLE gitops_ast_resource_mappings (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        file_id uuid NOT NULL,
        resource_type text NOT NULL,
        resource_name text NOT NULL,
        address text NOT NULL,
        start_line integer NOT NULL CHECK(start_line >= 1),
        end_line integer NOT NULL CHECK(end_line >= start_line),
        raw_attributes jsonb NOT NULL,
        cloud_resource_id text,
        match_tier varchar(20) NOT NULL DEFAULT 'deterministic',
        PRIMARY KEY(tenant_id,id),
        FOREIGN KEY(tenant_id,file_id) REFERENCES gitops_ast_files(tenant_id,id)
    )""",
}
INDEXES = (
    "CREATE INDEX cloud_drift_events_resource ON cloud_drift_events(tenant_id,canonical_resource_id,detected_at DESC)",
    "CREATE INDEX gitops_ast_cloud_resource ON gitops_ast_resource_mappings(tenant_id,cloud_resource_id)",
    "CREATE INDEX resource_baselines_lookup ON resource_state_baselines(tenant_id,canonical_resource_id)",
)


def sqlite_schema():
    statements = []
    for ddl in TABLES.values():
        for kind in ("uuid", "jsonb", "timestamptz"):
            ddl = ddl.replace(kind, "TEXT")
        statements.append(ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "))
    statements.extend(
        ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ") for ddl in INDEXES
    )
    return ";\n".join(statements) + ";"
