"""Persist v3 SaaS FOCUS and eBPF flow rows (migration 0030)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


class V3FinOpsStore:
    def __init__(self, store):
        self.store = store

    def insert_saas_focus_records(self, tenant_id: str, rows: list[dict]) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        with self.store.transaction(tenant_id, write=True) as db:
            for row in rows:
                db.execute(
                    """INSERT INTO saas_focus_billing_records
                       (tenant_id,id,provider_name,service_category,service_subcategory,resource_id,
                        sku_meter,commitment_discount_status,billed_cost_usd,effective_cost_usd,
                        charge_period_start,charge_period_end,payload,created_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        tenant_id,
                        str(uuid4()),
                        row["provider_name"],
                        row["service_category"],
                        row.get("service_subcategory") or "",
                        row.get("resource_id") or "",
                        row.get("sku_meter") or "",
                        row.get("commitment_discount_status") or "Unknown",
                        row["billed_cost_usd"],
                        row["effective_cost_usd"],
                        row["charge_period_start"],
                        row["charge_period_end"],
                        db.json(row.get("payload") or row),
                        now,
                    ),
                )
                inserted += 1
        return dict(inserted=inserted)

    def insert_ebpf_flows(self, tenant_id: str, rows: list[dict]) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        with self.store.transaction(tenant_id, write=True) as db:
            for row in rows:
                db.execute(
                    """INSERT INTO k8s_ebpf_flow_costs
                       (tenant_id,id,cluster_id,source_namespace,source_workload,source_az,
                        dest_namespace,dest_workload,dest_az,traffic_class,bytes_transferred,
                        attributed_cost_usd,window_start,window_end)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        tenant_id,
                        str(uuid4()),
                        row["cluster_id"],
                        row["source_namespace"],
                        row["source_workload"],
                        row["source_az"],
                        row.get("dest_namespace") or "",
                        row.get("dest_workload") or "",
                        row.get("dest_az") or "",
                        row["traffic_class"],
                        row["bytes_transferred"],
                        row["attributed_cost_usd"],
                        row["window_start"],
                        row["window_end"],
                    ),
                )
                inserted += 1
        return dict(inserted=inserted)
