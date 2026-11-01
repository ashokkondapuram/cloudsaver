"""v3.0 SaaS FOCUS and eBPF flow tables (migration 0030)."""

TABLES = {
    "saas_focus_billing_records": """CREATE TABLE saas_focus_billing_records (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        provider_name varchar(80) NOT NULL,
        service_category varchar(80) NOT NULL,
        service_subcategory varchar(80),
        resource_id text,
        sku_meter varchar(120),
        commitment_discount_status varchar(40),
        billed_cost_usd numeric(20,6) NOT NULL,
        effective_cost_usd numeric(20,6) NOT NULL,
        charge_period_start timestamptz NOT NULL,
        charge_period_end timestamptz NOT NULL,
        payload jsonb NOT NULL,
        created_at timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id)
    )""",
    "k8s_ebpf_flow_costs": """CREATE TABLE k8s_ebpf_flow_costs (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        cluster_id varchar(128) NOT NULL,
        source_namespace varchar(253) NOT NULL,
        source_workload varchar(253) NOT NULL,
        source_az varchar(40) NOT NULL,
        dest_namespace varchar(253),
        dest_workload varchar(253),
        dest_az varchar(40),
        traffic_class varchar(40) NOT NULL,
        bytes_transferred bigint NOT NULL CHECK(bytes_transferred >= 0),
        attributed_cost_usd numeric(20,6) NOT NULL,
        window_start timestamptz NOT NULL,
        window_end timestamptz NOT NULL,
        PRIMARY KEY(tenant_id,id)
    )""",
}
INDEXES = (
    "CREATE INDEX saas_focus_period ON saas_focus_billing_records(tenant_id,charge_period_start,charge_period_end)",
    "CREATE INDEX ebpf_flow_cluster ON k8s_ebpf_flow_costs(tenant_id,cluster_id,window_start)",
)


def sqlite_schema():
    statements = []
    for ddl in TABLES.values():
        for kind in ("uuid", "jsonb", "timestamptz"):
            ddl = ddl.replace(kind, "TEXT")
        ddl = ddl.replace("numeric(20,6)", "TEXT").replace("bigint", "INTEGER")
        statements.append(ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "))
    statements.extend(
        ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ") for ddl in INDEXES
    )
    return ";\n".join(statements) + ";"
