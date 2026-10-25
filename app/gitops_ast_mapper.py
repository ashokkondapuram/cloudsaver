"""Read-only Git resource index and IaC patch previews (v2 scaffold)."""

import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResourceMapping(BaseModel):
    cloud_resource_id: str
    repository: str
    file_path: str
    iac_kind: str
    model_config = ConfigDict(extra="forbid")


class PatchPreview(BaseModel):
    iac_kind: str
    file_path: str
    summary: str
    diff: str
    model_config = ConfigDict(extra="forbid")


class GitOpsAstMapper:
    def __init__(self, index: dict[str, dict[str, str]] | None = None):
        self._index = index if index is not None else self._load_index()

    @staticmethod
    def _load_index() -> dict[str, dict[str, str]]:
        raw = os.getenv("CLOUDSAVER_GITOPS_AST_INDEX") or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("CLOUDSAVER_GITOPS_AST_INDEX is not valid JSON")
        if not isinstance(data, dict):
            raise ValueError("CLOUDSAVER_GITOPS_AST_INDEX must be a JSON object")
        return data

    def lookup(self, resource_id: str) -> ResourceMapping:
        if not resource_id or len(resource_id) > 2048:
            raise ValueError("resource_id must be 1–2048 characters")
        entry = self._index.get(resource_id)
        if not entry:
            raise KeyError("mapping not found")
        return ResourceMapping(cloud_resource_id=resource_id, **entry)

    def patch_preview(self, mapping: ResourceMapping, change: dict[str, Any]) -> PatchPreview:
        kind = mapping.iac_kind.lower()
        if kind in ("terraform", "opentofu"):
            return PatchPreview(
                iac_kind=kind,
                file_path=mapping.file_path,
                summary="Terraform import block preview (advisory only)",
                diff="# preview only\nimport {\n  to = example.resource\n  id = \"...\"\n}\n",
            )
        raise NotImplementedError(f"Patch preview is not implemented for {mapping.iac_kind}")
