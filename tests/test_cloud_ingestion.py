"""Provider adapters are exercised offline with paged, malformed and foreign data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.cloud_http import JSONReader, pages
from app.cloud_scope import normalize_sources, validate_finding_scope
from app.multi_cloud import scan_multi_cloud
from tests.fixtures.synthetic_findings import demo_cloud_findings, demo_workspace
from app.scanner import RULES, ScanError
from app.scanner_gcp import scan_gcp_project, sql_idle_evidence, SQL_METRIC
from app.scanner_kubernetes import scan_cluster
from app.schemas import WasteFinding

PROJECT = 'test-cloudsaver'
GCP = {'project_id': PROJECT, 'regions': ['us-central1']}
NOW = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)


class Reader:
    def __init__(self, callback):
        self.callback, self.calls = callback, []
    def get(self, url, params=None):
        self.calls.append((url, params))
        return self.callback(url, params or {})


def compute(kind, name='archive', *, regional=False):
    location = 'regions/us-central1' if regional or kind == 'addresses' else 'zones/us-central1-a'
    value = dict(name=name, selfLink=f'https://www.googleapis.com/compute/v1/projects/{PROJECT}/{location}/{kind}/{name}',
                 users=[], status='READY' if kind == 'disks' else 'RESERVED')
    value['region' if location.startswith('regions') else 'zone'] = 'https://www.googleapis.com/compute/v1/projects/' + PROJECT + '/' + location
    if kind == 'addresses':
        value.update(addressType='EXTERNAL', ipVersion='IPV4')
    return value


def sql_series(*, point_count=336, value=0, project=PROJECT):
    return dict(metric={'type': SQL_METRIC}, resource={'type': 'cloudsql_database',
        'labels': {'project_id': project, 'database_id': f'{project}:staging-db'}},
        points=[{'interval': {'endTime': (NOW - timedelta(hours=i)).isoformat()},
                 'value': {'int64Value': str(value)}} for i in range(point_count)])


def test_gcp_zonal_regional_pagination_and_reserved_ipv4():
    disk, regional, address = compute('disks'), compute('disks', 'regional', regional=True), compute('addresses', 'unused-ip')
    def reply(url, params):
        if '/aggregated/disks' in url:
            if params.get('pageToken'):
                return {'items': {}}
            return {'items': {'zones/us-central1-a': {'disks': [disk]}}, 'nextPageToken': 'page-2'}
        if '/regions/us-central1/disks' in url:
            return {'items': [regional]}
        if '/aggregated/addresses' in url:
            associated, internal = deepcopy(address), deepcopy(address)
            associated.update(name='used', users=['instance'])
            associated['selfLink'] = associated['selfLink'].replace('unused-ip', 'used')
            internal.update(name='internal', addressType='INTERNAL')
            internal['selfLink'] = internal['selfLink'].replace('unused-ip', 'internal')
            return {'items': {'regions/us-central1': {'addresses': [address, associated, internal]}}}
        return {}
    reader = Reader(reply)
    findings = scan_gcp_project(GCP, reader=reader, now=NOW)
    assert len(findings) == 3
    assert sum(f['rule_id'] == 'GCP_UNATTACHED_DISK' for f in findings) == 2
    assert all(f['estimated_monthly_waste_usd'] is None for f in findings)
    assert any(p.get('pageToken') == 'page-2' for _, p in reader.calls)


@pytest.mark.parametrize('bad', ['foreign', 'partial', 'token', 'identity', 'late-failure'])
def test_gcp_refuses_partial_or_unauthorized_inventory(bad):
    disk = compute('disks')
    if bad == 'foreign':
        disk['selfLink'] = disk['selfLink'].replace(PROJECT, 'other-project')
    if bad == 'identity':
        disk['name'] = 'not-the-same-disk'
    def reply(url, params):
        if '/aggregated/disks' in url:
            if bad == 'partial':
                return {'items': {'zones/us-central1-a': {'warning': {'code': 'FORBIDDEN'}}}}
            result = {'items': {'zones/us-central1-a': {'disks': [disk]}}}
            if bad == 'token':
                result['nextPageToken'] = 'repeated'
            return result
        if bad == 'late-failure':
            raise RuntimeError('private provider failure')
        return {}
    with pytest.raises((ScanError, ValueError)):
        scan_gcp_project(GCP, reader=Reader(reply), now=NOW)


def test_cloud_sql_requires_every_hour_and_every_series():
    reader = Reader(lambda *_: {'timeSeries': [sql_series()]})
    evidence = sql_idle_evidence(reader, PROJECT, 'staging-db', NOW)
    assert evidence['aligned_hours'] == 336 and evidence['maximum_connections'] == 0
    for batch in [[], [sql_series(point_count=335)], [sql_series(value=1)], [sql_series(), sql_series(value=2)]]:
        assert sql_idle_evidence(Reader(lambda *_, batch=batch: {'timeSeries': batch}), PROJECT, 'staging-db', NOW) is None
    with pytest.raises(ScanError, match='outside'):
        sql_idle_evidence(Reader(lambda *_: {'timeSeries': [sql_series(project='foreign-cloud')]}), PROJECT, 'staging-db', NOW)


def test_cloud_sql_only_flags_explicit_dev_environment_with_complete_evidence():
    def reply(url, params):
        if url.endswith('/instances'):
            return {'items': [dict(project=PROJECT, name='staging-db', region='us-central1', state='RUNNABLE',
                                   settings={'userLabels': {'environment': 'staging'}}),
                              dict(project=PROJECT, name='prod-db', region='us-central1', state='RUNNABLE', settings={})]}
        if url.endswith('/timeSeries'):
            return {'timeSeries': [sql_series()]}
        return {}
    result = scan_gcp_project(GCP, reader=Reader(reply), now=NOW)
    assert len(result) == 1 and result[0]['rule_id'] == 'GCP_IDLE_CLOUD_SQL'
    assert result[0]['evidence']['series_count'] == 1


def metric_reader(*, samples=337, usage=.4, cluster='test-cluster', warning=False, duplicate=False):
    def reply(url, params):
        query = params['query']
        value = (2 if 'resource_requests' in query else usage)
        rows = [{'metric': dict(cluster=cluster, namespace='staging', pod='api-worker', container='api'),
                 'values': [[int((NOW - timedelta(hours=i)).timestamp()), str(value)] for i in range(samples)]}]
        return dict(status='success', data={'resultType': 'matrix', 'result': rows * (2 if duplicate else 1)},
                    **({'warnings': ['partial remote read']} if warning else {}))
    return Reader(reply)


CLUSTER = dict(cluster_id='test-cluster', prometheus_url='https://prometheus.example.test', bearer_token_env='CLOUDSAVER_PROMETHEUS_TOKEN_TEST')


def test_kubernetes_p95_and_full_window_evidence():
    results = scan_cluster(CLUSTER, reader=metric_reader(), now=NOW)
    assert {r['rule_id'] for r in results} == {'K8S_CPU_OVERSIZED', 'K8S_MEMORY_OVERSIZED'}
    for result in results:
        evidence = result['evidence']
        assert evidence['samples'] == 337 and evidence['p95_usage'] == .4
        assert evidence['suggested_request_with_50pct_headroom'] == pytest.approx(.6)
        assert result['estimated_monthly_waste_usd'] is None
    assert scan_cluster(CLUSTER, reader=metric_reader(samples=336), now=NOW) == []
    assert scan_cluster(CLUSTER, reader=metric_reader(usage=1.5), now=NOW) == []


@pytest.mark.parametrize('options', [dict(cluster='foreign-cluster'), dict(warning=True), dict(duplicate=True), dict(usage='NaN')])
def test_kubernetes_rejects_bad_or_ambiguous_metrics(options):
    with pytest.raises(ScanError):
        scan_cluster(CLUSTER, reader=metric_reader(**options), now=NOW)


def test_http_reader_refuses_redirects_and_invalid_payloads():
    for response in [httpx.Response(302, headers={'Location': 'https://other.test'}), httpx.Response(200, json=[]), httpx.Response(503)]:
        reader = JSONReader(transport=httpx.MockTransport(lambda _, r=response: r))
        try:
            with pytest.raises(ScanError):
                reader.get('https://example.test')
        finally:
            reader.close()
    with pytest.raises(ScanError, match='continuation'):
        list(pages(Reader(lambda *_: {'nextPageToken': 'repeat'}), 'https://example.test'))


def test_synthetic_fixtures_are_scope_checked_for_all_providers():
    tenant = dict(subscription_ids=['22222222-2222-4222-8222-222222222222'])
    values = demo_cloud_findings(demo_workspace(tenant), ['azure', 'aws', 'gcp', 'kubernetes'])
    assert len(values) == 21
    for item in values:
        WasteFinding.model_validate(item)
        validate_finding_scope(item, demo_workspace(tenant))
        assert item['details'].startswith('TEST FIXTURE:')
    assert len(RULES) == 7
    with pytest.raises(ScanError):
        scan_multi_cloud(tenant, ['gcp'])


@pytest.mark.parametrize('entry', [dict(gcp_projects=[{'project_id': '../../foreign', 'regions': ['us-central1']}]),
    dict(kubernetes_clusters=[dict(CLUSTER, prometheus_url='http://localhost')]),
    dict(kubernetes_clusters=[dict(CLUSTER, bearer_token_env='STRIPE_SECRET_KEY')]),
    dict(aws_accounts=[dict(account_id='123456789012', region='us-east-1')])])
def test_operator_source_validation(entry):
    with pytest.raises(ValueError):
        normalize_sources(entry)


def test_operator_sources_roundtrip_without_credentials():
    result = normalize_sources(dict(gcp_projects=[GCP], kubernetes_clusters=[CLUSTER],
              aws_accounts=[dict(account_id='123456789012', region='us-east-1', credential_profile='customer-a')]))
    assert result['gcp_projects'] == [GCP]
