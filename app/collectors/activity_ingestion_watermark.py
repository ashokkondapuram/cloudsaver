"""Incremental Stream D watermarks per scope (last ingested activity event time)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

_WATERMARK_KEY = 'activity_ingestion_watermark'


def _max_event_time(evidence: dict) -> str | None:
    events = evidence.get('activity_events') or []
    if not isinstance(events, list) or not events:
        return None
    best = ''
    for item in events:
        if not isinstance(item, dict):
            continue
        t = str(item.get('event_time') or '')
        if t and t > best:
            best = t
    return best or None


def merge_scope_watermarks(inventory: list[dict]) -> dict[str, str]:
    """Return scope_id -> max ISO event time from inventory evidence."""
    merged: dict[str, str] = {}
    for row in inventory:
        if not isinstance(row, dict):
            continue
        scope = row.get('scope_id') or row.get('subscription_id')
        if not scope:
            continue
        evidence = row.get('evidence') or {}
        if not isinstance(evidence, dict):
            continue
        t = _max_event_time(evidence)
        if not t:
            continue
        key = str(scope)
        if key not in merged or t > merged[key]:
            merged[key] = t
    return merged


def apply_watermarks_to_inventory(inventory: list[dict], *, previous: dict[str, str] | None = None) -> None:
    """Set evidence.activity_ingestion_watermark on rows; merge *previous* scope maxima."""
    prev = dict(previous or {})
    current = merge_scope_watermarks(inventory)
    for scope, t in current.items():
        if scope not in prev or t > prev[scope]:
            prev[scope] = t
    for row in inventory:
        if not isinstance(row, dict):
            continue
        scope = str(row.get('scope_id') or row.get('subscription_id') or '')
        if not scope:
            continue
        stamp = prev.get(scope)
        if not stamp:
            continue
        ev = row.setdefault('evidence', {})
        if not isinstance(ev, dict):
            continue
        existing = ev.get(_WATERMARK_KEY)
        block: dict[str, Any]
        if isinstance(existing, dict):
            block = dict(existing)
        elif isinstance(existing, str):
            try:
                block = dict(json.loads(existing))
            except (json.JSONDecodeError, TypeError):
                block = {}
        else:
            block = {}
        block['last_ingested_event_time'] = stamp
        block['scopes'] = dict(sorted(prev.items()))
        ev[_WATERMARK_KEY] = block


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_previous_scope_watermarks_from_scan(scan: dict | None) -> dict[str, str]:
    """Recover scope_id -> max watermark time from a prior completed scan inventory."""
    if not scan or not isinstance(scan, dict):
        return {}
    merged: dict[str, str] = {}
    for row in scan.get('inventory') or []:
        if not isinstance(row, dict):
            continue
        scope = str(row.get('scope_id') or row.get('subscription_id') or '')
        if not scope:
            continue
        ev = row.get('evidence') or {}
        if not isinstance(ev, dict):
            continue
        block = ev.get(_WATERMARK_KEY)
        if isinstance(block, str):
            try:
                block = json.loads(block)
            except (json.JSONDecodeError, TypeError):
                block = None
        if not isinstance(block, dict):
            continue
        scopes_map = block.get('scopes')
        if isinstance(scopes_map, dict):
            for sid, t in scopes_map.items():
                if not isinstance(sid, str) or not isinstance(t, str) or not t:
                    continue
                if sid not in merged or t > merged[sid]:
                    merged[sid] = t
        else:
            stamp = block.get('last_ingested_event_time')
            if isinstance(stamp, str) and stamp:
                if scope not in merged or stamp > merged[scope]:
                    merged[scope] = stamp
    return merged
