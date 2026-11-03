"""Engineering action catalog: every supported action is zero-downtime by policy."""
from __future__ import annotations

from typing import Literal

DowntimeClass = Literal["zero_downtime"]

# id -> (analysis rule code, human summary, whether an agent resize step is ever allowed)
ACTIONS: dict[str, dict[str, str | bool]] = {
    "azure.vm.rightsize": {
        "rule_id": "CS-AZ-VM-RIGHTSIZING",
        "summary": "Review VM SKU change without deallocate/stop cycles",
        "allows_agent_resize": True,
    },
    "azure.disk.review": {
        "rule_id": "CS-AZ-DISK-UNATTACHED",
        "summary": "Review unattached disk retention; no destructive execution",
        "allows_agent_resize": False,
    },
    "azure.storage.lifecycle.review": {
        "rule_id": "CS-AZ-STORAGE-LIFECYCLE",
        "summary": "Review blob lifecycle and multipart cleanup; configuration only",
        "allows_agent_resize": False,
    },
}


def downtime_class(_action_id: str) -> DowntimeClass:
    return "zero_downtime"


def resize_arguments(*, action_id: str, target_size: str) -> dict[str, str | bool]:
    """Bounded compute.resize arguments for an approved engineering execution."""
    if action_id not in ACTIONS:
        raise ValueError("Unknown engineering action")
    if not ACTIONS[action_id]["allows_agent_resize"]:
        raise ValueError("This engineering action is evidence-only and never mutates compute")
    if not target_size or len(target_size) > 80:
        raise ValueError("target_size is required and must be at most 80 characters")
    return dict(target_size=target_size, resize_mode="zero_downtime", restore_power=False)
