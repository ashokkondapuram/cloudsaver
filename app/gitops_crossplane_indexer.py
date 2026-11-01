"""Crossplane XRD, Composition, and Usage indexing (v2/v3 scaffold)."""
from __future__ import annotations

from typing import Any


def index_manifest(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract reconciled external resource hints from Crossplane YAML objects."""
    kind = str(document.get("kind") or "")
    api = str(document.get("apiVersion") or "")
    if not kind or not api:
        return []
    if kind == "CompositeResourceDefinition":
        return [dict(kind=kind, api_version=api, name=document.get("metadata", {}).get("name"))]
    if kind in ("Composition", "Usage"):
        return [dict(kind=kind, api_version=api, name=document.get("metadata", {}).get("name"))]
    if api.endswith("crossplane.io/v1") or "/aws.upbound.io/" in api or "/azure.upbound.io/" in api:
        return [
            dict(
                kind=kind,
                api_version=api,
                name=document.get("metadata", {}).get("name"),
                external_name=document.get("metadata", {}).get("annotations", {}).get("crossplane.io/external-name"),
            )
        ]
    return []
