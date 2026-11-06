"""Normalize Stream D activity (Activity Log, CloudTrail, Cloud Audit) for analysis."""
from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_IAC_PATTERNS = ('terraform', 'github-actions', 'cloudformation')
MAX_ACTIVITY_EVENTS = 20


def iac_principal_patterns() -> tuple[str, ...]:
    raw = os.getenv('CLOUDSAVER_IAC_PRINCIPAL_PATTERNS', '')
    if raw.strip():
        return tuple(part.strip().lower() for part in raw.split(',') if part.strip())
    return DEFAULT_IAC_PATTERNS


def is_iac_authorized(actor_identity: str) -> bool:
    actor = (actor_identity or '').lower()
    if not actor:
        return False
    return any(pattern in actor for pattern in iac_principal_patterns())


def _iso_time(value: Any) -> str:
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _changed_field_names(mapping: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(mapping, dict):
        return []
    keys = [str(k) for k in mapping.keys() if k]
    keys.sort()
    return keys[:limit]


def normalize_activity_event(*, provider: str, payload: dict) -> dict | None:
    """Return a dict compatible with analysis_service.context.ActivityEvent."""
    provider_key = (provider or '').lower()
    if provider_key == 'azure':
        return _normalize_azure(payload)
    if provider_key == 'aws':
        return _normalize_aws(payload)
    if provider_key == 'gcp':
        return _normalize_gcp(payload)
    return None


def _normalize_azure(event: dict) -> dict | None:
    event_id = event.get('eventDataId') or event.get('id')
    if not event_id:
        return None
    operation = (event.get('operationName') or {}).get('value') or ''
    claims = event.get('claims') or {}
    actor = (
        claims.get('appid')
        or claims.get('name')
        or claims.get('upn')
        or event.get('caller')
        or ''
    )
    props = event.get('properties') or {}
    changed = _changed_field_names(props.get('responseBody') or props.get('requestbody') or props)
    return dict(
        event_id=str(event_id),
        event_time=_iso_time(event.get('eventTimestamp')),
        event_name=str(operation),
        actor_identity=str(actor),
        changed_fields=changed,
        is_iac_authorized=is_iac_authorized(str(actor)),
    )


def _normalize_aws(event: dict) -> dict | None:
    event_id = event.get('EventId')
    if not event_id:
        return None
    body: dict = {}
    raw = event.get('CloudTrailEvent')
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                body = parsed
        except json.JSONDecodeError:
            body = {}
    elif isinstance(raw, dict):
        body = raw
    identity = body.get('userIdentity') or {}
    actor = (
        identity.get('arn')
        or identity.get('userName')
        or identity.get('principalId')
        or event.get('Username')
        or ''
    )
    request = body.get('requestParameters') or {}
    changed = _changed_field_names(request if isinstance(request, dict) else {})
    name = event.get('EventName') or body.get('eventName') or ''
    event_time = event.get('EventTime') or body.get('eventTime')
    return dict(
        event_id=str(event_id),
        event_time=_iso_time(event_time),
        event_name=str(name),
        actor_identity=str(actor),
        changed_fields=changed,
        is_iac_authorized=is_iac_authorized(str(actor)),
    )


def _normalize_gcp(entry: dict) -> dict | None:
    insert_id = entry.get('insertId')
    if not insert_id:
        return None
    payload = entry.get('protoPayload') or {}
    auth = payload.get('authenticationInfo') or {}
    actor = auth.get('principalEmail') or auth.get('principalSubject') or ''
    request = payload.get('request') or {}
    changed = _changed_field_names(request if isinstance(request, dict) else {})
    return dict(
        event_id=str(insert_id),
        event_time=_iso_time(entry.get('timestamp')),
        event_name=str(payload.get('methodName') or ''),
        actor_identity=str(actor),
        changed_fields=changed,
        is_iac_authorized=is_iac_authorized(str(actor)),
    )


def append_activity_events(evidence: dict, normalized: list[dict], *, limit: int = MAX_ACTIVITY_EVENTS) -> None:
    if not normalized:
        return
    bucket = evidence.setdefault('activity_events', [])
    for item in normalized:
        if len(bucket) >= limit:
            break
        if isinstance(item, dict) and item.get('event_id'):
            bucket.append(item)
