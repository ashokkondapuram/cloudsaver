"""Optional Cloud Asset searchAllResources inventory (additive to ListAssets)."""
import json
import os

from app.cloud_http import post_pages
from app.collectors.gcp_live import ASSET_TYPES, inventory_rows_from_asset


def asset_search_enabled() -> bool:
    return os.getenv('CLOUDSAVER_GCP_ASSET_SEARCH', '').lower() in ('1', 'true', 'yes')


def search_url(project: str) -> str:
    return 'https://cloudasset.googleapis.com/v1/projects/' + project + ':searchAllResources'


def asset_from_search_result(item: dict) -> dict:
    kind = item.get('assetType')
    rid = item.get('name', '')
    location = item.get('location')
    data = dict(labels=item.get('labels') or {})
    state = item.get('state')
    if state:
        data['status'] = state
        data['state'] = state
    for versioned in item.get('versionedResources') or []:
        if not isinstance(versioned, dict):
            continue
        raw = versioned.get('resource')
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
        elif isinstance(raw, dict):
            parsed = raw
        else:
            continue
        if isinstance(parsed, dict):
            data.update(parsed)
    return dict(assetType=kind, name=rid, resource=dict(location=location, data=data))


def search_inventory_rows(reader, project, regions):
    rows = []
    body = {'assetTypes': list(ASSET_TYPES), 'pageSize': 500}
    for page in post_pages(reader, search_url(project), body):
        for item in page.get('results', []):
            if not isinstance(item, dict):
                continue
            rows.extend(inventory_rows_from_asset(asset_from_search_result(item), project, regions))
    return rows
