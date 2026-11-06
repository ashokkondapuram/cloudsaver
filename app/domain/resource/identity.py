"""Canonical cloud resource identifiers and stable lookup keys."""
from __future__ import annotations

import hashlib


def canonical_resource_id(provider: str, resource_id: str) -> str:
    """Return the provider-normalized resource id used for matching and hashing.

    Rules:
    - **azure**: strip leading/trailing whitespace, then lowercase (ARM ids are case-insensitive).
    - **aws**, **gcp**, **k8s**, and all other providers: strip whitespace only; case is preserved
      (e.g. AWS ARNs remain case-sensitive).
    """
    value = (resource_id or '').strip()
    if provider == 'azure':
        return value.lower()
    return value


def resource_key(provider: str, resource_id: str) -> str:
    """Stable 64-char hex key: SHA-256 of ``provider|canonical_resource_id``."""
    canonical = canonical_resource_id(provider, resource_id)
    return hashlib.sha256(f'{provider}|{canonical}'.encode()).hexdigest()
