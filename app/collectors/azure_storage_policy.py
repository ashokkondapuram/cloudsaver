"""Read Azure Storage account management policies for FinOps lifecycle analysis."""
from __future__ import annotations

from typing import Any

import httpx

from app.collectors.azure_endpoint import arm_url, validate_arm_resource_path
from app.collectors.azure_configuration_evidence import enrich_configuration_evidence
from app.collectors.live_common import collect
from app.provider_retry import ProviderReadError, read_json

_POLICY_API = '2023-01-01'
_STORAGE = 'microsoft.storage/storageaccounts'


def _walk_delete_actions(actions: dict) -> list[dict]:
    deletes: list[dict] = []
    if not isinstance(actions, dict):
        return deletes
    for key in ('baseBlob', 'snapshot', 'version'):
        block = actions.get(key)
        if not isinstance(block, dict):
            continue
        delete = block.get('delete')
        if isinstance(delete, dict):
            deletes.append(delete)
    return deletes


def parse_management_policy(body: dict | None, *, absent: bool = False) -> dict[str, Any]:
    """Map ARM management policy JSON to FinOps evidence fields."""
    if absent or body is None:
        return dict(
            lifecycle_policy_verified=True,
            multipart_abort_rule_present=False,
            lifecycle_policy_rule_count=0,
        )
    rules = (((body.get('properties') or {}).get('policy') or {}).get('rules')) or []
    if not isinstance(rules, list):
        raise ValueError('Invalid storage management policy')
    enabled = [rule for rule in rules if isinstance(rule, dict) and rule.get('enabled') is not False]
    lifecycle_verified = bool(enabled)
    multipart_abort = False
    abort_days: int | None = None
    for rule in enabled:
        definition = rule.get('definition') or {}
        actions = definition.get('actions') or {}
        for delete in _walk_delete_actions(actions):
            abort = delete.get('abortIncompleteMultipartUpload')
            if isinstance(abort, dict):
                days = abort.get('daysAfterCreationGreaterThan')
                if type(days) is int and days >= 0:
                    abort_days = days if abort_days is None else min(abort_days, days)
                    multipart_abort = multipart_abort or days <= 7
    out: dict[str, Any] = dict(
        lifecycle_policy_verified=lifecycle_verified,
        multipart_abort_rule_present=multipart_abort,
        lifecycle_policy_rule_count=len(enabled),
    )
    if type(abort_days) is int:
        out['abort_incomplete_multipart_days'] = abort_days
    return out


def _fetch_policy(reader, resource_id: str, scope_lower: str) -> tuple[dict | None, bool]:
    validate_arm_resource_path(resource_id, scope_path_lower=scope_lower)
    url = arm_url(f'{resource_id.rstrip("/")}/managementPolicies/default')
    params = {'api-version': _POLICY_API}
    headers: dict[str, str] = {}
    if reader.headers_factory:
        full = str(httpx.URL(url, params=params))
        headers.update(reader.headers_factory(full))
        params = None
    try:
        body = read_json(reader.client, 'GET', url, params=params, headers=headers, quota_key=reader.quota_key(url))
    except ProviderReadError as error:
        if error.status_code == 404:
            return None, True
        raise
    if not isinstance(body, dict):
        raise ValueError('Invalid storage management policy response')
    return body, False


def enrich_storage_row(reader, resource) -> dict:
    if (resource.get('resource_type') or '').lower() != _STORAGE:
        return resource
    rid = resource.get('resource_id') or ''
    scope = rid.split('/providers/')[0].lower() if '/providers/' in rid else ''
    evidence = resource.setdefault('evidence', {})

    def load():
        body, absent = _fetch_policy(reader, rid, scope)
        parsed = parse_management_policy(body, absent=absent)
        evidence.update(parsed)
        return parsed

    collect(evidence, 'storage_management_policy', load)
    enrich_configuration_evidence(resource)
    return resource


def enrich_storage_management_policies(reader, inventory, *, settings=None) -> list[dict]:
    """Attach lifecycle policy evidence to Azure storage account inventory rows."""
    del settings  # reserved for future platform limits
    for resource in inventory:
        enrich_storage_row(reader, resource)
    return inventory
