"""Declarative JSON rules as catalog rows; no CloudSaver ``app`` package dependency."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger('platform.identity.declarative_catalog')

_DECL_RULES_CACHE: tuple[tuple[str, int] | None, tuple[dict[str, Any], ...]] = (None, ())


def clear_declarative_rules_cache_for_tests() -> None:
    global _DECL_RULES_CACHE
    _DECL_RULES_CACHE = (None, ())


def _declarative_rules_path() -> str | None:
    raw = os.getenv('CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES', '').strip()
    return raw or None


def load_declarative_rules() -> tuple[dict[str, Any], ...]:
    path = _declarative_rules_path()
    if not path:
        return ()
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        logger.exception('Declarative rules path missing: %s', path)
        return ()
    cache_key = (str(p.resolve()), getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))
    global _DECL_RULES_CACHE
    if _DECL_RULES_CACHE[0] == cache_key:
        return _DECL_RULES_CACHE[1]
    try:
        payload = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        logger.exception('Declarative rules unreadable or invalid: %s', path)
        return ()
    if not isinstance(payload, dict):
        logger.warning('Declarative rules root must be an object')
        return ()
    rules = payload.get('rules')
    if not isinstance(rules, list):
        logger.warning('Declarative rules missing "rules" array')
        return ()
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rules):
        if not isinstance(row, dict):
            continue
        rid = str(row.get('id') or '').strip()
        if not rid.startswith('PLATFORM_') or len(rid) > 120:
            logger.warning('Declarative rule %s: id must start with PLATFORM_', i)
            continue
        pillar_raw = str(row.get('pillar') or '').strip()
        if not pillar_raw:
            logger.warning('Declarative rule %s: invalid pillar', rid)
            continue
        action = str(row.get('remediation_action') or 'Review platform declarative rule').strip()
        if len(action) > 2000:
            action = action[:2000]
        display_name = str(row.get('display_name') or '').strip() or None
        when = row.get('when') or {}
        if not isinstance(when, dict) or 'all' not in when:
            logger.warning('Declarative rule %s: missing when.all', rid)
            continue
        preds = when.get('all')
        if not isinstance(preds, list) or not preds:
            logger.warning('Declarative rule %s: when.all must be a non-empty list', rid)
            continue
        out.append(
            dict(
                id=rid,
                pillar=pillar_raw,
                remediation_action=action,
                predicates=preds,
                display_name=display_name,
            ),
        )
    built = tuple(out)
    _DECL_RULES_CACHE = (cache_key, built)
    return built


def _legacy_pillar(pillar_name: str) -> str:
    key = pillar_name.upper().replace('-', '_')
    if key == 'SECURITY':
        return 'security'
    if key == 'COST_OPTIMIZATION':
        return 'cost'
    if key == 'PERFORMANCE_EFFICIENCY':
        return 'performance'
    if key == 'RELIABILITY':
        return 'reliability'
    return 'operations'


def extend_resource_catalog_definitions(
    rule_display_names: dict[str, str],
) -> list[tuple]:
    """Append catalog definition rows for JSON rules; update ``rule_display_names`` in place."""
    rows: list[tuple] = []
    for rule in load_declarative_rules():
        rid = rule['id']
        title = (rule.get('display_name') or '').strip() or 'Declarative policy rule'
        rule_display_names[rid] = title
        legacy = _legacy_pillar(str(rule['pillar']))
        rows.append((rid, 'platform', 'policy', '*', title, legacy, {}))
    return rows
