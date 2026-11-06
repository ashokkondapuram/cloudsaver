"""Declarative JSON rules merged into platform pillar evaluators.

Point ``CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES`` at a JSON file (UTF-8). Schema::

    {
      "version": 1,
      "rules": [
        {
          "id": "PLATFORM_JSON_EXAMPLE",
          "display_name": "Optional catalog title shown in /api/v1/rules/catalog",
          "pillar": "COST_OPTIMIZATION",
          "severity": "MEDIUM",
          "remediation_action": "Short operator instruction",
          "when": {
            "all": [
              {"provider_in": ["aws", "azure"]},
              {"resource_type_matches": ".*compute.*"},
              {"tag_missing": "cost_center"},
              {"env_not_in": ["prod", "production"]}
            ]
          }
        }
      ]
    }

Supported predicates inside ``when.all`` (all must match):

- ``provider_in``: list of provider strings
- ``resource_type_matches``: regex (case-insensitive) against ``ctx.resource_type``
- ``tag_present`` / ``tag_missing``: tag key (case-insensitive)
- ``tag_equals``: ``{"key": "env", "value": "prod"}``
- ``env_in`` / ``env_not_in``: lists compared to ``ctx.env_label()`` (lowercase)

Rules emit ``PillarFinding`` rows with evidence ``{source: declarative_rules, rule: <id>}``.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id

logger = logging.getLogger('cloudsaver.analysis')


def _path() -> str | None:
    raw = os.getenv('CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES', '').strip()
    return raw or None


_DECL_RULES_CACHE: tuple[tuple[str, int] | None, tuple] = (None, ())


def clear_declarative_rules_cache_for_tests() -> None:
    global _DECL_RULES_CACHE
    _DECL_RULES_CACHE = (None, ())


def load_declarative_rules() -> tuple[dict[str, Any], ...]:
    """Return tuple of normalized rule dicts; reload when path or mtime changes."""
    path = _path()
    if not path:
        clear_declarative_rules_cache_for_tests()
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
        text = p.read_text(encoding='utf-8')
    except OSError:
        logger.exception('Declarative rules file unreadable: %s', path)
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.exception('Declarative rules JSON invalid: %s', path)
        return ()
    if not isinstance(payload, dict):
        logger.warning('Declarative rules root must be an object')
        return ()
    rules = payload.get('rules')
    if not isinstance(rules, list):
        logger.warning('Declarative rules missing "rules" array')
        return ()
    out = []
    for i, row in enumerate(rules):
        if not isinstance(row, dict):
            continue
        rid = str(row.get('id') or '').strip()
        if not rid.startswith('PLATFORM_') or len(rid) > 120:
            logger.warning('Declarative rule %s: id must start with PLATFORM_', i)
            continue
        try:
            pillar = Pillar(str(row['pillar']))
        except (KeyError, ValueError):
            logger.warning('Declarative rule %s: invalid pillar', rid)
            continue
        try:
            severity = Severity(str(row['severity']))
        except (KeyError, ValueError):
            logger.warning('Declarative rule %s: invalid severity', rid)
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
                pillar=pillar,
                severity=severity,
                remediation_action=action,
                predicates=preds,
                display_name=display_name,
            )
        )
    built = tuple(out)
    _DECL_RULES_CACHE = (cache_key, built)
    return built


def _pred_matches(ctx: UnifiedResourceContext, pred: Any) -> bool:
    if not isinstance(pred, dict) or len(pred) != 1:
        return False
    key, value = next(iter(pred.items()))
    if key == 'provider_in':
        return isinstance(value, list) and ctx.provider in {str(v) for v in value}
    if key == 'resource_type_matches':
        if not isinstance(value, str):
            return False
        try:
            return bool(re.search(value, ctx.resource_type or '', re.I))
        except re.error:
            return False
    if key == 'tag_present':
        if not isinstance(value, str):
            return False
        return ctx.tag(value) is not None
    if key == 'tag_missing':
        if not isinstance(value, str):
            return False
        return ctx.tag(value) is None
    if key == 'tag_equals':
        if not isinstance(value, dict):
            return False
        k, v = value.get('key'), value.get('value')
        if not isinstance(k, str) or not isinstance(v, str):
            return False
        actual = ctx.tag(k)
        return actual is not None and actual.lower() == v.lower()
    if key == 'env_in':
        if not isinstance(value, list):
            return False
        env = ctx.env_label()
        if not env:
            return False
        return env in {str(v).lower() for v in value}
    if key == 'env_not_in':
        if not isinstance(value, list):
            return False
        env = ctx.env_label() or ''
        forbidden = {str(v).lower() for v in value}
        return env not in forbidden
    return False


def extend_resource_catalog_definitions() -> list[tuple]:
    """Append catalog definition rows for JSON rules; update ``RULE_DISPLAY_NAMES`` in place."""
    from app.resource_catalog import RULE_DISPLAY_NAMES

    rows = []
    for rule in load_declarative_rules():
        rid = rule['id']
        title = (rule.get('display_name') or '').strip() or 'Declarative policy rule'
        RULE_DISPLAY_NAMES[rid] = title
        pillar_name = rule['pillar'].value if hasattr(rule['pillar'], 'value') else str(rule['pillar'])
        if pillar_name == 'SECURITY':
            legacy = 'security'
        elif pillar_name == 'COST_OPTIMIZATION':
            legacy = 'cost'
        elif pillar_name == 'PERFORMANCE_EFFICIENCY':
            legacy = 'performance'
        elif pillar_name == 'RELIABILITY':
            legacy = 'reliability'
        else:
            legacy = 'operations'
        rows.append((rid, 'platform', 'policy', '*', title, legacy, {}))
    return rows


def evaluate_declarative_rules(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    findings: list[PillarFinding] = []
    for rule in load_declarative_rules():
        ok = True
        for pred in rule['predicates']:
            if not _pred_matches(ctx, pred):
                ok = False
                break
        if not ok:
            continue
        rid = rule['id']
        pillar = rule['pillar']
        findings.append(
            PillarFinding(
                finding_id=deterministic_finding_id(canonical_id=ctx.canonical_id, pillar=pillar, rule_id=rid),
                pillar=pillar,
                rule_id=rid,
                severity=rule['severity'],
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                region=ctx.region,
                resource_type=ctx.resource_type,
                current_sku=ctx.current_sku,
                evidence={
                    'source': 'declarative_rules',
                    'rule': rid,
                    **({'display_name': rule['display_name']} if rule.get('display_name') else {}),
                },
                remediation_action=rule['remediation_action'],
            )
        )
    return findings
