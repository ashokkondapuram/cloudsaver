"""0036 — per ARM resource type tables with Azure-aligned columns and dual cost columns."""
from alembic import op

revision = "0036_typed_resource_tables"
down_revision = "0035_resource_type_catalog"
branch_labels = depends_on = None

OWNER = (
    "tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid"
)


def _create_table(name: str, specific_sql: str) -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{name} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            scan_id UUID NOT NULL REFERENCES public.scans(id) ON DELETE CASCADE,
            resource_id TEXT NOT NULL,
            subscription_id UUID NOT NULL,
            resource_group TEXT NOT NULL,
            name TEXT NOT NULL,
            location TEXT,
            tags JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            observed_at TIMESTAMPTZ NOT NULL,
            arm_api_version TEXT,
            provisioning_state TEXT,
            {specific_sql},
            reporting_currency CHAR(3) NOT NULL,
            cost_period_start DATE,
            cost_period_end DATE,
            azure_billed NUMERIC(24,8),
            azure_effective NUMERIC(24,8),
            azure_list NUMERIC(24,8),
            cost_center_billed NUMERIC(24,8),
            cost_center_effective NUMERIC(24,8),
            cost_center_list NUMERIC(24,8),
            azure_charge_count INTEGER NOT NULL DEFAULT 0,
            cost_center_charge_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE (scan_id, resource_id)
        );
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{name}_tenant_scan ON public.{name} (tenant_id, scan_id)")
    op.execute(f"ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{name} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{name} TO cloudsaver_app")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON public.{name}
            FOR ALL TO cloudsaver_app
            USING ({OWNER})
            WITH CHECK ({OWNER});
        """
    )


def upgrade():
    from app.typed_resources.azure_schemas import ALL_TYPED_TABLES

    for spec in ALL_TYPED_TABLES:
        _create_table(spec["table"], spec["specific_sql"].strip().rstrip(","))


def downgrade():
    from app.typed_resources.azure_schemas import ALL_TYPED_TABLES

    for spec in ALL_TYPED_TABLES:
        op.execute(f"DROP TABLE IF EXISTS public.{spec['table']}")
