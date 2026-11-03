"""Public Azure Resource Manager endpoint profile (release gate: no sovereign/custom hosts)."""
from __future__ import annotations

from urllib.parse import urlsplit

ARM_RESOURCE = "https://management.azure.com/.default"
ARM_ROOT = "https://management.azure.com"
ARM_HOST = "management.azure.com"


def arm_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return ARM_ROOT + path


def validate_arm_resource_path(resource_id: str, *, scope_path_lower: str) -> None:
    """Reject resource IDs outside the expected subscription or resource-group scope."""
    path = (resource_id or "").strip().lower()
    scope = scope_path_lower.lower().rstrip("/")
    if not path.startswith("/subscriptions/") or not path.startswith(f"{scope}/"):
        raise ValueError("Invalid Azure resource scope")


def validate_arm_https_url(url: str, *, scope_path_lower: str) -> None:
    """Reject token-bearing or off-profile continuation URLs."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != ARM_HOST
        or not parsed.path.lower().startswith(scope_path_lower + "/")
    ):
        raise ValueError("Invalid Azure continuation")
