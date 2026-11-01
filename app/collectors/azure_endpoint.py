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


def validate_arm_https_url(url: str, *, scope_path_lower: str) -> None:
    """Reject token-bearing or off-profile continuation URLs."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != ARM_HOST
        or not parsed.path.lower().startswith(scope_path_lower + "/")
    ):
        raise ValueError("Invalid Azure continuation")
