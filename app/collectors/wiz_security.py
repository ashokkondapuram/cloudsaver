"""Stream F — Wiz cloud security issues (optional, read-only GraphQL)."""
from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlencode, urlsplit

import httpx

from app.cloud_http import JSONReader
from app.domain.resource.identity import canonical_resource_id
from app.provider_retry import read_json, shared_budget

logger = logging.getLogger('cloudsaver.scanner')

_DEFAULT_AUTH = 'https://auth.app.wiz.io/oauth/token'
_ISSUES_V2_QUERY = """query IssuesV2($after: String, $first: Int!, $filterBy: IssueFilters) {
  issuesV2(after: $after, first: $first, filterBy: $filterBy) {
    nodes {
      id
      status
      severity
      createdAt
      sourceRule { id name }
      entitySnapshot {
        id
        type
        name
        nativeType
        externalId
        cloudPlatform
        region
        providerId
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""


def enabled(settings=None) -> bool:
    from app.cloudsaver_platform_settings import integration_flag

    return integration_flag(settings, 'wiz_security_enabled', 'CLOUDSAVER_WIZ_ENABLED', default='false')


def _auth_url() -> str:
    return (os.getenv('CLOUDSAVER_WIZ_AUTH_URL') or _DEFAULT_AUTH).strip()


def _graphql_url() -> str:
    raw = (os.getenv('CLOUDSAVER_WIZ_GRAPHQL_URL') or '').strip()
    if not raw:
        return ''
    parsed = urlsplit(raw)
    if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.app.wiz.io'):
        logger.warning('CLOUDSAVER_WIZ_GRAPHQL_URL must be https and host must end with .app.wiz.io')
        return ''
    if not (parsed.path or '').rstrip('/').endswith('/graphql'):
        logger.warning('CLOUDSAVER_WIZ_GRAPHQL_URL path must end with /graphql')
        return ''
    return raw


def _client_credentials() -> tuple[str, str]:
    cid = (os.getenv('CLOUDSAVER_WIZ_CLIENT_ID') or '').strip()
    secret = (os.getenv('CLOUDSAVER_WIZ_CLIENT_SECRET') or '').strip()
    return cid, secret


def _page_size() -> int:
    raw = (os.getenv('CLOUDSAVER_WIZ_PAGE_SIZE') or '100').strip()
    try:
        n = int(raw)
    except ValueError:
        return 100
    return max(1, min(n, 500))


def _max_nodes() -> int:
    raw = (os.getenv('CLOUDSAVER_WIZ_MAX_ISSUES') or '5000').strip()
    try:
        n = int(raw)
    except ValueError:
        return 5000
    return max(1, min(n, 50000))


def _issue_filter() -> dict:
    """Default: open, critical/high/medium (override via JSON in CLOUDSAVER_WIZ_ISSUE_FILTER)."""
    import json

    raw = (os.getenv('CLOUDSAVER_WIZ_ISSUE_FILTER') or '').strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning('CLOUDSAVER_WIZ_ISSUE_FILTER is not valid JSON; using defaults')
    return {
        'status': ['OPEN', 'IN_PROGRESS'],
        'severity': ['CRITICAL', 'HIGH', 'MEDIUM'],
    }


def _fetch_token(client: httpx.Client) -> str:
    cid, secret = _client_credentials()
    if not cid or not secret:
        raise ValueError('Wiz client id/secret not configured')
    auth_url = _auth_url()
    budget = shared_budget()
    body = urlencode(
        {
            'grant_type': 'client_credentials',
            'audience': 'wiz-api',
            'client_id': cid,
            'client_secret': secret,
        }
    )
    result = read_json(
        client,
        'POST',
        auth_url,
        content=body.encode('utf-8'),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        quota_key=urlsplit(auth_url).netloc + ':wiz-token',
        read_only_post=True,
        interval=0.25,
        budget=budget,
    )
    token = result.get('access_token')
    if not isinstance(token, str) or not token:
        raise ValueError('Wiz token response missing access_token')
    return token


def _graphql_post(client: httpx.Client, url: str, token: str, variables: dict) -> dict:
    budget = shared_budget()
    return read_json(
        client,
        'POST',
        url,
        json={'query': _ISSUES_V2_QUERY, 'variables': variables},
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
        quota_key=urlsplit(url).netloc + ':wiz-graphql',
        read_only_post=True,
        interval=0.25,
        budget=budget,
    )


def _normalize_issue(node: dict) -> dict | None:
    if not isinstance(node, dict) or not node.get('id'):
        return None
    snap = node.get('entitySnapshot') if isinstance(node.get('entitySnapshot'), dict) else {}
    rule = node.get('sourceRule') if isinstance(node.get('sourceRule'), dict) else {}
    return dict(
        source='wiz',
        issue_id=str(node['id']),
        status=str(node.get('status') or ''),
        severity=str(node.get('severity') or ''),
        rule_id=str(rule.get('id') or ''),
        rule_name=str(rule.get('name') or ''),
        entity_id=str(snap.get('id') or ''),
        entity_name=str(snap.get('name') or ''),
        native_type=str(snap.get('nativeType') or snap.get('type') or ''),
        external_id=str(snap.get('externalId') or ''),
        cloud_platform=str(snap.get('cloudPlatform') or ''),
        region=str(snap.get('region') or ''),
        provider_id=str(snap.get('providerId') or ''),
    )


def fetch_wiz_issues() -> list[dict]:
    """Pull all configured Wiz issues (bounded by CLOUDSAVER_WIZ_MAX_ISSUES)."""
    gql = _graphql_url()
    if not gql:
        return []
    cid, secret = _client_credentials()
    if not cid or not secret:
        logger.warning('Wiz enabled but CLOUDSAVER_WIZ_CLIENT_ID/SECRET not set')
        return []
    first = _page_size()
    cap = _max_nodes()
    filt = _issue_filter()
    out: list[dict] = []
    with httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0), follow_redirects=False) as client:
        token = _fetch_token(client)
        after = None
        while len(out) < cap:
            variables = {'first': min(first, cap - len(out)), 'after': after, 'filterBy': filt}
            payload = _graphql_post(client, gql, token, variables)
            errs = payload.get('errors')
            if isinstance(errs, list) and errs:
                logger.warning('Wiz GraphQL returned errors: %s', errs[:3])
            data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
            block = data.get('issuesV2') if isinstance(data.get('issuesV2'), dict) else {}
            nodes = block.get('nodes')
            if not isinstance(nodes, list):
                break
            for node in nodes:
                norm = _normalize_issue(node if isinstance(node, dict) else {})
                if norm:
                    out.append(norm)
            page = block.get('pageInfo') if isinstance(block.get('pageInfo'), dict) else {}
            if not page.get('hasNextPage'):
                break
            after = page.get('endCursor')
            if not after:
                break
            time.sleep(0.05)
    return out


def _wiz_provider_key(cloud_platform: str) -> str:
    p = (cloud_platform or '').strip().upper()
    if p in ('AWS', 'AMAZON_WEB_SERVICES'):
        return 'aws'
    if p in ('AZURE', 'MICROSOFT_AZURE'):
        return 'azure'
    if p in ('GCP', 'GOOGLE_CLOUD', 'GOOGLE_CLOUD_PLATFORM'):
        return 'gcp'
    return ''


def _match_resource_id(issue: dict, *, row_provider: str, row_rid: str) -> bool:
    ext = (issue.get('external_id') or '').strip()
    pid = (issue.get('provider_id') or '').strip()
    if ext and canonical_resource_id(row_provider, ext) == canonical_resource_id(row_provider, row_rid):
        return True
    if pid and canonical_resource_id(row_provider, pid) == canonical_resource_id(row_provider, row_rid):
        return True
    return False


def enrich_inventory_wiz_signals(inventory: list[dict], settings=None) -> list[dict]:
    """Attach evidence.wiz_issues[] to inventory rows when Wiz entity id matches resource_id."""
    if not enabled(settings) or not inventory:
        return inventory
    try:
        issues = fetch_wiz_issues()
    except Exception:
        logger.exception('Wiz issue fetch failed')
        return inventory
    by_key: dict[str, dict[str, dict]] = {}
    for issue in issues:
        wp = _wiz_provider_key(str(issue.get('cloud_platform') or ''))
        if not wp:
            continue
        ext = (issue.get('external_id') or '').strip()
        pid = (issue.get('provider_id') or '').strip()
        iid = str(issue.get('issue_id') or '')
        if not iid:
            continue
        payload = {k: v for k, v in issue.items() if k != 'cloud_platform'}
        for rid in (ext, pid):
            if not rid:
                continue
            key = canonical_resource_id(wp, rid)
            by_key.setdefault(key, {})[iid] = payload

    for resource in inventory:
        provider = resource.get('cloud_provider') or 'azure'
        rid = resource.get('resource_id') or ''
        if not rid:
            continue
        key = canonical_resource_id(str(provider), rid)
        matched_map = by_key.get(key)
        matched = list(matched_map.values()) if matched_map else []
        if not matched:
            fallback = [
                {k: v for k, v in i.items() if k != 'cloud_platform'}
                for i in issues
                if _wiz_provider_key(str(i.get('cloud_platform'))) == str(provider) and _match_resource_id(i, row_provider=str(provider), row_rid=str(rid))
            ]
            dedupe_fb: dict[str, dict] = {}
            for item in fallback:
                fid = str(item.get('issue_id') or '')
                if fid:
                    dedupe_fb[fid] = item
            matched = list(dedupe_fb.values())
        if matched:
            resource.setdefault('evidence', {})['wiz_issues'] = matched
    return inventory


def enrich_inventory_wiz_from_reader(reader: JSONReader, inventory: list[dict], settings=None) -> list[dict]:
    """Signature parity with other enrich(inventory) helpers; Wiz uses env creds, not the ARM/GCP reader."""
    del reader
    return enrich_inventory_wiz_signals(inventory, settings=settings)
