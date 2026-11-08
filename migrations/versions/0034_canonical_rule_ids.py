"""0034 — normalize legacy finding rule_id values to catalog identifiers."""
from alembic import op
import sqlalchemy as sa

revision = "0034_canonical_rule_ids"
down_revision = "0033_platform_outbox_lease"
branch_labels = depends_on = None

_CASE = """
CASE rule_id
  WHEN 'ORPHANED_DISK' THEN 'AZURE_DISK_UNATTACHED_RETENTION'
  WHEN 'ORPHANED_DISKS' THEN 'AZURE_DISK_UNATTACHED_RETENTION'
  WHEN 'UNASSOCIATED_PUBLIC_IP' THEN 'AZURE_PUBLIC_IP_UNASSOCIATED'
  WHEN 'UNASSOCIATED_PUBLIC_IPS' THEN 'AZURE_PUBLIC_IP_UNASSOCIATED'
  WHEN 'STOPPED_VM' THEN 'AZURE_VM_STOPPED_RESIDUAL_COST'
  WHEN 'STOPPED_VMS' THEN 'AZURE_VM_STOPPED_RESIDUAL_COST'
  WHEN 'EMPTY_APP_SERVICE_PLAN' THEN 'AZURE_ASP_EMPTY_PAID_PLAN'
  WHEN 'EMPTY_APP_SERVICE' THEN 'AZURE_ASP_EMPTY_PAID_PLAN'
  WHEN 'UNDERUTILIZED_VM' THEN 'AZURE_VM_RIGHTSIZING_UTILIZATION'
  WHEN 'UNDERUTILIZED_APP_SERVICE_PLAN' THEN 'AZURE_ASP_UNDERUTILIZED_SKU'
  WHEN 'IDLE_APP_GATEWAY' THEN 'AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR'
  WHEN 'K8S_CPU_OVERSIZED' THEN 'K8S_CONTAINER_CPU_OVERREQUEST'
  WHEN 'K8S_MEMORY_OVERSIZED' THEN 'K8S_CONTAINER_MEMORY_OVERREQUEST'
  ELSE rule_id
END
"""

_LEGACY = (
    "ORPHANED_DISK",
    "ORPHANED_DISKS",
    "UNASSOCIATED_PUBLIC_IP",
    "UNASSOCIATED_PUBLIC_IPS",
    "STOPPED_VM",
    "STOPPED_VMS",
    "EMPTY_APP_SERVICE_PLAN",
    "EMPTY_APP_SERVICE",
    "UNDERUTILIZED_VM",
    "UNDERUTILIZED_APP_SERVICE_PLAN",
    "IDLE_APP_GATEWAY",
    "K8S_CPU_OVERSIZED",
    "K8S_MEMORY_OVERSIZED",
)


_BATCH_SIZE = 500


def _migrate_scan_payloads(connection):
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from app.rule_id_canonical import normalize_scan

    last_id = None
    while True:
        if last_id is None:
            rows = connection.execute(
                sa.text("SELECT id, payload FROM public.scans ORDER BY id LIMIT :limit"),
                {"limit": _BATCH_SIZE},
            ).fetchall()
        else:
            rows = connection.execute(
                sa.text(
                    "SELECT id, payload FROM public.scans WHERE id > :last_id ORDER BY id LIMIT :limit"
                ),
                {"last_id": last_id, "limit": _BATCH_SIZE},
            ).fetchall()
        if not rows:
            break
        for scan_id, payload in rows:
            if isinstance(payload, dict):
                normalized = normalize_scan(payload)
                if normalized != payload:
                    connection.execute(
                        sa.text("UPDATE public.scans SET payload = CAST(:payload AS jsonb) WHERE id = :id"),
                        {"id": scan_id, "payload": json.dumps(normalized)},
                    )
        last_id = rows[-1][0]
        if len(rows) < _BATCH_SIZE:
            break


def upgrade():
    bind = op.get_bind()
    in_list = ", ".join(f"'{value}'" for value in _LEGACY)
    tables = ("public.waste_findings", "public.cloud_findings", "public.scans")
    # RLS tables are FORCE-protected with no tenant set during a migration, so a
    # non-superuser migration owner (as managed Postgres providers require) would
    # match zero rows here. Lift FORCE for the statements below, inside this
    # migration's own transaction, and restore it immediately after.
    for table in tables:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    try:
        for table in ("public.waste_findings", "public.cloud_findings"):
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET rule_id = {_CASE} WHERE rule_id IN ({in_list})"
                )
            )
        _migrate_scan_payloads(bind)
    finally:
        for table in tables:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def downgrade():
    reverse = {
        "AZURE_DISK_UNATTACHED_RETENTION": "ORPHANED_DISK",
        "AZURE_PUBLIC_IP_UNASSOCIATED": "UNASSOCIATED_PUBLIC_IP",
        "AZURE_VM_STOPPED_RESIDUAL_COST": "STOPPED_VM",
        "AZURE_ASP_EMPTY_PAID_PLAN": "EMPTY_APP_SERVICE_PLAN",
        "AZURE_VM_RIGHTSIZING_UTILIZATION": "UNDERUTILIZED_VM",
        "AZURE_ASP_UNDERUTILIZED_SKU": "UNDERUTILIZED_APP_SERVICE_PLAN",
        "AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR": "IDLE_APP_GATEWAY",
        "K8S_CONTAINER_CPU_OVERREQUEST": "K8S_CPU_OVERSIZED",
        "K8S_CONTAINER_MEMORY_OVERREQUEST": "K8S_MEMORY_OVERSIZED",
    }
    bind = op.get_bind()
    tables = ("public.waste_findings", "public.cloud_findings")
    for table in tables:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    try:
        for catalog, legacy in reverse.items():
            for table in tables:
                bind.execute(
                    sa.text(f"UPDATE {table} SET rule_id = :legacy WHERE rule_id = :catalog"),
                    {"legacy": legacy, "catalog": catalog},
                )
    finally:
        for table in tables:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
