"""Draft Karpenter NodePool manifests from SLO inputs (v2 scaffold)."""

from typing import Any


def draft_node_pool(name: str, instance_types: list[str], cpu_limit: str, consolidation: str = "WhenEmpty") -> dict[str, Any]:
    if not name or not instance_types:
        raise ValueError("name and instance_types are required")
    return {
        "apiVersion": "karpenter.sh/v1",
        "kind": "NodePool",
        "metadata": {"name": name},
        "spec": {
            "template": {
                "spec": {
                    "requirements": [
                        {"key": "karpenter.sh/capacity-type", "operator": "In", "values": ["on-demand", "spot"]},
                        {"key": "node.kubernetes.io/instance-type", "operator": "In", "values": instance_types},
                    ],
                    "limits": {"cpu": cpu_limit},
                }
            },
            "disruption": {"consolidationPolicy": consolidation},
        },
    }


def draft_aks_nap_node_pool(name: str, vm_sizes: list[str], max_count: int) -> dict[str, Any]:
    if not name or not vm_sizes or max_count < 1:
        raise ValueError("name, vm_sizes and max_count are required")
    return {
        "apiVersion": "karpenter.azure.com/v1alpha1",
        "kind": "AKSNodeClass",
        "metadata": {"name": name},
        "spec": {"vmSize": vm_sizes[0], "maxPods": 110, "maxCount": max_count, "vmSizes": vm_sizes},
    }
