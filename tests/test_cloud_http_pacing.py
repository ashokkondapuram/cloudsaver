import httpx

from app.cloud_http import JSONReader, _json_reader_pacing_interval


def test_json_reader_passes_pacing_interval(monkeypatch):
    captured = {}

    def read_json(client, method, url, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr('app.cloud_http.read_json', read_json)
    monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT', 'production')
    monkeypatch.setenv('CLOUDSAVER_JSON_READER_INTERVAL_SECONDS', '0.5')
    reader = JSONReader(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    reader.get('https://management.azure.com/subscriptions/x/resourceGroups/r')
    reader.close()
    assert captured['interval'] == 0.5


def test_json_reader_pacing_disabled_in_development(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_ENVIRONMENT', 'development')
    assert _json_reader_pacing_interval() == 0.0
