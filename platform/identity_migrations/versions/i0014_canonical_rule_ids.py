"""Remap legacy analysis rule catalog ids to CloudSaver catalog identifiers."""
revision = 'i0014_canonical_rule_ids'
down_revision = 'i0013_multicloud_analysis_catalog'
branch_labels = None
depends_on = None

_MAP = (
    ('ORPHANED_DISK', 'AZURE_DISK_UNATTACHED_RETENTION'),
    ('ORPHANED_DISKS', 'AZURE_DISK_UNATTACHED_RETENTION'),
    ('UNASSOCIATED_PUBLIC_IP', 'AZURE_PUBLIC_IP_UNASSOCIATED'),
    ('UNASSOCIATED_PUBLIC_IPS', 'AZURE_PUBLIC_IP_UNASSOCIATED'),
    ('STOPPED_VM', 'AZURE_VM_STOPPED_RESIDUAL_COST'),
    ('STOPPED_VMS', 'AZURE_VM_STOPPED_RESIDUAL_COST'),
    ('EMPTY_APP_SERVICE_PLAN', 'AZURE_ASP_EMPTY_PAID_PLAN'),
    ('EMPTY_APP_SERVICE', 'AZURE_ASP_EMPTY_PAID_PLAN'),
    ('UNDERUTILIZED_VM', 'AZURE_VM_RIGHTSIZING_UTILIZATION'),
    ('UNDERUTILIZED_APP_SERVICE_PLAN', 'AZURE_ASP_UNDERUTILIZED_SKU'),
    ('IDLE_APP_GATEWAY', 'AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR'),
    ('K8S_CPU_OVERSIZED', 'K8S_CONTAINER_CPU_OVERREQUEST'),
    ('K8S_MEMORY_OVERSIZED', 'K8S_CONTAINER_MEMORY_OVERREQUEST'),
)


def upgrade():
    from alembic import op
    for legacy, catalog in _MAP:
        op.execute(
            f"UPDATE analysis.workspace_rule_overrides SET rule_id = '{catalog}' WHERE rule_id = '{legacy}'"
        )
        op.execute(f"DELETE FROM analysis.rule_catalog WHERE id = '{legacy}'")


def downgrade():
    pass
