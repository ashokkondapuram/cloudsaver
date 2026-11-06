"""Smoke tests for app.collectors._pagination helpers."""
from __future__ import annotations

import pytest

from app.collectors._pagination import cloud_http_pages, iter_arm_next_link_values
from app.cloud_http import pages as cloud_pages


class Reader:
    def __init__(self, callback):
        self.callback = callback
        self.calls: list[tuple] = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self.callback(url, params or {})


def test_iter_arm_next_link_values_follows_next_link():
    base = 'https://management.azure.com/subscriptions/x/providers/Microsoft.Compute/disks'
    link = base + '?api-version=2024-03-01&$skiptoken=abc'

    def reply(url, params):
        if url == base:
            return {'value': [{'name': 'd1'}], 'nextLink': link}
        if url == link:
            return {'value': [{'name': 'd2'}]}
        raise AssertionError(url)

    reader = Reader(reply)
    assert list(iter_arm_next_link_values(reader, base, {'api-version': '2024-03-01'})) == [
        {'name': 'd1'},
        {'name': 'd2'},
    ]
    assert reader.calls[0] == (base, {'api-version': '2024-03-01'})
    assert reader.calls[1] == (link, None)


def test_iter_arm_next_link_values_rejects_repeated_link():
    base = 'https://management.azure.com/subscriptions/x/providers/Microsoft.Compute/disks'
    payload = {'value': [], 'nextLink': base + '?$skiptoken=x'}

    reader = Reader(lambda url, params: payload)
    with pytest.raises(ValueError, match='continuation'):
        list(iter_arm_next_link_values(reader, base))


def test_cloud_http_pages_delegates_to_cloud_http():
    def reply(url, params):
        if params.get('pageToken'):
            return {'items': [2]}
        return {'items': [1], 'nextPageToken': 't1'}

    reader_a = Reader(reply)
    pages_a = list(cloud_http_pages(reader_a, 'https://example.test/list', {'pageSize': 2}, param_key='pageToken'))
    reader_b = Reader(reply)
    pages_b = list(cloud_pages(reader_b, 'https://example.test/list', {'pageSize': 2}, param_key='pageToken'))
    assert [p['items'] for p in pages_a] == [[1], [2]]
    assert pages_a == pages_b
