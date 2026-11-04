"""Shared scan payload indexing for validation scripts (matches API list semantics)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

DEFAULT_SAMPLE_TYPES = int(__import__('os').getenv('VALIDATE_SAMPLE_TYPES', '6'))
DEFAULT_PER_TYPE = int(__import__('os').getenv('VALIDATE_PER_TYPE', '2'))
DEFAULT_FINDING_SAMPLE = int(__import__('os').getenv('VALIDATE_FINDING_SAMPLE', '3'))


def pick_resource_samples(
    items: list[dict],
    *,
    max_types: int | None = None,
    max_per_type: int | None = None,
) -> list[dict]:
    """Up to N resource types, M rows each; prefer ARM detail collected."""
    type_limit = max_types if max_types is not None else DEFAULT_SAMPLE_TYPES
    per_type = max_per_type if max_per_type is not None else DEFAULT_PER_TYPE
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in items:
        buckets[(row.get('resource_type') or 'unknown').lower()].append(row)
    out: list[dict] = []
    for rtype in sorted(buckets.keys())[:type_limit]:
        rows = buckets[rtype]
        rows.sort(key=lambda r: (0 if r.get('arm_detail') == 'collected' else 1, r.get('resource_name') or ''))
        out.extend(rows[:per_type])
    return out


def sample_findings(findings: list[dict], *, max_items: int | None = None) -> list[dict]:
    """Spread sampled findings across rule_id (cap total)."""
    cap = max_items if max_items is not None else DEFAULT_FINDING_SAMPLE
    if len(findings) <= cap:
        return findings
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_rule[f.get('rule_id') or 'unknown'].append(f)
    out: list[dict] = []
    for rule_id in sorted(by_rule.keys()):
        if len(out) >= cap:
            break
        out.append(by_rule[rule_id][0])
    for f in findings:
        if len(out) >= cap:
            break
        if f not in out:
            out.append(f)
    return out[:cap]


def expand_subscription_ids(base: list[str], resource_ids: list[str]) -> list[str]:
    subs = {s.lower() for s in base}
    for rid in resource_ids:
        parts = (rid or '').split('/')
        if len(parts) > 2 and parts[1].lower() == 'subscriptions':
            subs.add(parts[2].lower())
    return sorted(str(UUID(s)) for s in subs)


def payload_index(payload: dict) -> dict[str, tuple[str, dict]]:
    """Map resource_id -> ('inventory'|'finding', row). Inventory wins when both exist."""
    out: dict[str, tuple[str, dict]] = {}
    for f in payload.get('findings') or []:
        rid = (f.get('resource_id') or '').lower()
        if rid:
            out[rid] = ('finding', f)
    for obs in payload.get('inventory') or []:
        rid = (obs.get('resource_id') or '').lower()
        if rid:
            out[rid] = ('inventory', obs)
    return out


def compare_api_to_db_record(api_row: dict, kind: str, db_row: dict) -> list[str]:
    issues: list[str] = []
    pairs = (
        ('resource_name', 'resource_name'),
        ('resource_type', 'resource_type'),
        ('resource_group', 'resource_group'),
    )
    for db_field, api_field in pairs:
        if (db_row.get(db_field) or '') != (api_row.get(api_field) or ''):
            issues.append(f'{db_field} mismatch ({kind})')
    return issues


def compare_api_db(api_items: list[dict], db_payload: dict) -> dict[str, Any]:
    index = payload_index(db_payload)
    issues: list[str] = []
    for row in api_items:
        rid = (row.get('resource_id') or '').lower()
        hit = index.get(rid)
        if not hit:
            issues.append(f'missing in db findings/inventory: {row.get("resource_key")}')
            continue
        issues.extend(compare_api_to_db_record(row, hit[0], hit[1]))
    api_ids = {(r.get('resource_id') or '').lower() for r in api_items}
    indexed_ids = set(index)
    return {
        'api_count': len(api_items),
        'db_inventory_count': len(db_payload.get('inventory') or []),
        'db_findings_count': len(db_payload.get('findings') or []),
        'db_index_count': len(indexed_ids),
        'api_not_in_db_count': len([i for i in issues if i.startswith('missing')]),
        'extra_db_only': len(indexed_ids - api_ids),
        'issues_count': len(issues),
        'issues_sample': issues[:15],
    }
