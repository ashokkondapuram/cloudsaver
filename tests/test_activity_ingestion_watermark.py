"""Activity ingestion scope watermarks on scan inventory."""

from app.collectors.activity_ingestion_watermark import (
    apply_watermarks_to_inventory,
    load_previous_scope_watermarks_from_scan,
    merge_scope_watermarks,
)


def test_merge_scope_watermarks_max_per_scope():
    inv = [
        {
            'scope_id': 'sub-1',
            'evidence': {'activity_events': [{'event_time': '2026-01-01T00:00:00Z'}]},
        },
        {
            'scope_id': 'sub-1',
            'evidence': {'activity_events': [{'event_time': '2026-02-01T00:00:00Z'}]},
        },
    ]
    assert merge_scope_watermarks(inv) == {'sub-1': '2026-02-01T00:00:00Z'}


def test_load_previous_scope_watermarks_from_scan():
    prev = {
        'inventory': [
            {
                'scope_id': 'a',
                'evidence': {
                    'activity_ingestion_watermark': {
                        'last_ingested_event_time': '2026-01-15T00:00:00Z',
                        'scopes': {'a': '2026-01-15T00:00:00Z', 'b': '2026-01-10T00:00:00Z'},
                    }
                },
            }
        ]
    }
    loaded = load_previous_scope_watermarks_from_scan(prev)
    assert loaded['a'] == '2026-01-15T00:00:00Z'
    assert loaded['b'] == '2026-01-10T00:00:00Z'


def test_apply_watermarks_merges_previous():
    inv = [
        {
            'scope_id': 'x',
            'evidence': {'activity_events': [{'event_time': '2026-03-01T00:00:00Z'}]},
        }
    ]
    apply_watermarks_to_inventory(inv, previous={'x': '2026-01-01T00:00:00Z'})
    wm = inv[0]['evidence']['activity_ingestion_watermark']
    assert wm['last_ingested_event_time'] == '2026-03-01T00:00:00Z'
    assert wm['scopes']['x'] == '2026-03-01T00:00:00Z'
