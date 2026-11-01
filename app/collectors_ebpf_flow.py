"""eBPF flow batch ingestion and cost attribution (v3 scaffold)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any


TRAFFIC_CLASSES = frozenset({"intra_az", "cross_az", "nat_gateway", "privatelink", "internet"})


def normalize_flow_record(record: dict[str, Any]) -> dict[str, Any]:
    traffic = str(record.get("traffic_class") or "").lower()
    if traffic not in TRAFFIC_CLASSES:
        raise ValueError("Invalid traffic_class")
    bytes_val = int(record["bytes_transferred"])
    if bytes_val < 0:
        raise ValueError("bytes_transferred must be nonnegative")
    rate = Decimal(str(record.get("usd_per_gb") or "0"))
    cost = (Decimal(bytes_val) / Decimal(1024**3)) * rate
    return dict(
        cluster_id=str(record["cluster_id"]),
        source_namespace=str(record.get("source_namespace") or ""),
        source_workload=str(record.get("source_workload") or ""),
        source_az=str(record.get("source_az") or ""),
        dest_namespace=str(record.get("dest_namespace") or ""),
        dest_workload=str(record.get("dest_workload") or ""),
        dest_az=str(record.get("dest_az") or ""),
        traffic_class=traffic,
        bytes_transferred=bytes_val,
        attributed_cost_usd=format(cost, "f"),
        window_start=str(record["window_start"]),
        window_end=str(record["window_end"]),
    )


def topology_routing_manifest(prefer_close: bool = True) -> dict[str, Any]:
    return dict(
        apiVersion="v1",
        kind="Service",
        metadata=dict(name="topology-aware-placeholder"),
        spec=dict(trafficDistribution="PreferClose" if prefer_close else "PreferSameZone"),
    )
