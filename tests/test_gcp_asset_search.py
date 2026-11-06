"""GCP Cloud Asset searchAllResources optional inventory path."""
import pytest

from app.collectors.gcp_asset_search import asset_from_search_result, search_inventory_rows, search_url
from app.collectors.gcp_live import extra_inventory

PROJECT = 'demo-project'
REGIONS = ['us-central1']
INSTANCE_RID = '//compute.googleapis.com/projects/' + PROJECT + '/zones/us-central1-a/instances/web-1'
SEARCH_ONLY_RID = '//run.googleapis.com/projects/' + PROJECT + '/locations/us-central1/services/batch-job'


class MockReader:
    def __init__(self, *, list_assets=None, search_pages=None):
        self.list_assets = list_assets or []
        self.search_pages = search_pages or []
        self.get_calls = []
        self.post_calls = []

    def get(self, url, params=None):
        self.get_calls.append((url, dict(params or {})))
        if self.list_assets:
            return self.list_assets.pop(0)
        return {'assets': []}

    def post_read(self, url, body):
        self.post_calls.append((url, dict(body)))
        if self.search_pages:
            return self.search_pages.pop(0)
        return {'results': []}


def list_asset(rid=INSTANCE_RID):
    return {
        'assetType': 'compute.googleapis.com/Instance',
        'name': rid,
        'resource': {
            'location': 'us-central1-a',
            'data': {'status': 'RUNNING', 'id': 42, 'labels': {'env': 'prod'}},
        },
    }


def search_result(rid, *, asset_type='run.googleapis.com/Service', location='us-central1'):
    return {
        'name': rid,
        'assetType': asset_type,
        'location': location,
        'state': 'ACTIVE',
        'labels': {'environment': 'staging'},
        'versionedResources': [
            {'resource': '{"template":{"scaling":{"minInstanceCount":1}}}'},
        ],
    }


def test_asset_search_disabled_uses_list_assets_only(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_GCP_ASSET_SEARCH', raising=False)
    reader = MockReader(list_assets=[{'assets': [list_asset()]}])
    rows = extra_inventory(reader, PROJECT, REGIONS)
    assert len(rows) == 1
    assert rows[0]['resource_id'] == INSTANCE_RID
    assert reader.post_calls == []


def test_asset_search_additive_and_dedupes(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_GCP_ASSET_SEARCH', 'true')
    reader = MockReader(
        list_assets=[{'assets': [list_asset()]}],
        search_pages=[
            {'results': [search_result(INSTANCE_RID), search_result(SEARCH_ONLY_RID)], 'nextPageToken': 'page-2'},
            {'results': []},
        ],
    )
    rows = extra_inventory(reader, PROJECT, REGIONS)
    assert {row['resource_id'] for row in rows} == {INSTANCE_RID, SEARCH_ONLY_RID}
    assert reader.post_calls[0][0] == search_url(PROJECT)
    assert reader.post_calls[0][1]['assetTypes']
    assert reader.post_calls[1][1]['pageToken'] == 'page-2'


def test_search_inventory_rows_paginates_with_mock_reader():
    reader = MockReader(
        search_pages=[
            {'results': [search_result(SEARCH_ONLY_RID)], 'nextPageToken': 'tok'},
            {'results': []},
        ]
    )
    rows = search_inventory_rows(reader, PROJECT, REGIONS)
    assert len(rows) == 1
    assert rows[0]['resource_type'] == 'run.googleapis.com/Service'
    assert rows[0]['evidence']['nonproduction'] is True
    assert reader.post_calls[1][1]['pageToken'] == 'tok'


def test_asset_from_search_result_merges_versioned_resource():
    item = search_result(SEARCH_ONLY_RID)
    asset = asset_from_search_result(item)
    assert asset['resource']['data']['template']['scaling']['minInstanceCount'] == 1


def test_search_rejects_foreign_project():
    foreign = search_result('//compute.googleapis.com/projects/other/zones/us-central1-a/instances/x')
    with pytest.raises(ValueError, match='unrelated resource'):
        search_inventory_rows(
            MockReader(search_pages=[{'results': [foreign]}]),
            PROJECT,
            REGIONS,
        )
