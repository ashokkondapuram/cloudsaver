"""Draft Karpenter NodePool manifests from SLO inputs (v2 scaffold)."""

import re
from typing import Any

_VALID_CONSOLIDATION = frozenset({"WhenEmpty", "WhenUnderutilized", "WhenEmptyOrUnderutilized"})
_CPU_LIMIT_RE = re.compile(r"^[1-9]\d*(\.\d+)?([eEinumkKMGTP]+%?)?$|^[1-9]\d*(\.\d+)?m$")


def _validate_cpu_limit(cpu_limit: str) -> str:
    if not isinstance(cpu_limit, str) or not cpu_limit.strip():
        raise ValueError("cpu_limit must be a non-empty Kubernetes quantity")
    value = cpu_limit.strip()
    if not _CPU_LIMIT_RE.fullmatch(value):
        raise ValueError("cpu_limit must be a positive Kubernetes quantity")
    if value.endswith("m"):
        if float(value[:-1]) <= 0:
            raise ValueError("cpu_limit must be a positive Kubernetes quantity")
    else:
        head = re.match(r"^(\d+(\.\d+)?)", value)
        if head and float(head.group(1)) <= 0:
            raise ValueError("cpu_limit must be a positive Kubernetes quantity")
    return value


def draft_node_pool(name: str, instance_types: list[str], cpu_limit: str, consolidation: str = "WhenEmpty") -> dict[str, Any]:
    if not name or not instance_types:
        raise ValueError("name and instance_types are required")
    if consolidation not in _VALID_CONSOLIDATION:
        raise ValueError(f"consolidation must be one of: {', '.join(sorted(_VALID_CONSOLIDATION))}")
    cpu_limit = _validate_cpu_limit(cpu_limit)
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
