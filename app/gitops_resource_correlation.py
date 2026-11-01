"""Three-tier cloud resource to IaC mapping (deterministic, structural, semantic)."""
from __future__ import annotations

from typing import Any


def correlate_resource(
    resource: dict[str, Any],
    *,
    env_index: dict[str, dict[str, str]],
    pgvector_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    rid = resource.get("resource_id") or ""
    if rid in env_index:
        return dict(tier="deterministic_id", mapping=env_index[rid])
    tags = resource.get("tags") or resource.get("evidence") or {}
    for key in ("terraform_address", "crossplane.io/claim-name", "git_repo"):
        if tags.get(key) and rid in env_index:
            return dict(tier="deterministic_tag", mapping=env_index[rid])
    provider = resource.get("cloud_provider")
    family = resource.get("resource_type")
    name = resource.get("resource_name") or resource.get("name")
    for entry in env_index.values():
        if entry.get("provider") == provider and entry.get("resource_family") == family and entry.get("name") == name:
            return dict(tier="structural", mapping=entry)
    if pgvector_matches:
        best = pgvector_matches[0]
        return dict(tier="semantic", mapping=best, score=best.get("score"))
    return None
