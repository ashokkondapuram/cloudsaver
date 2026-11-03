"""0035 — catalog of Azure resource types and ARM API versions for inventory detail."""
from alembic import op

revision = "0035_resource_type_catalog"
down_revision = "0034_canonical_rule_ids"
branch_labels = depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.resource_type_catalog (
            provider TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            arm_api_version TEXT NOT NULL,
            evidence_schema_version TEXT NOT NULL DEFAULT '3',
            normalized_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
            PRIMARY KEY (provider, resource_type)
        );
        """
    )
    op.execute("ALTER TABLE public.resource_type_catalog ENABLE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT ON public.resource_type_catalog TO cloudsaver_app")
    op.execute(
        """
        CREATE POLICY resource_type_catalog_read ON public.resource_type_catalog
            FOR SELECT TO cloudsaver_app USING (true);
        """
    )
    # Seed matches app/azure_resource_registry.py (operator-maintained).
    op.execute(
        """
        INSERT INTO public.resource_type_catalog (provider, resource_type, arm_api_version, normalized_fields)
        VALUES
          ('azure', 'microsoft.compute/disks', '2023-04-02', '["diskSizeGB","diskState","encryption"]'::jsonb),
          ('azure', 'microsoft.compute/virtualmachines', '2022-11-01', '["hardwareProfile","storageProfile","networkProfile"]'::jsonb),
          ('azure', 'microsoft.network/publicipaddresses', '2023-05-01', '["publicIPAllocationMethod","sku"]'::jsonb),
          ('azure', 'microsoft.storage/storageaccounts', '2023-01-01', '["sku","accessTier","encryption"]'::jsonb),
          ('azure', 'microsoft.containerservice/managedclusters', '2024-01-01', '["kubernetesVersion","agentPoolProfiles"]'::jsonb)
        ON CONFLICT (provider, resource_type) DO UPDATE SET
            arm_api_version = EXCLUDED.arm_api_version,
            normalized_fields = EXCLUDED.normalized_fields;
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS public.resource_type_catalog")
