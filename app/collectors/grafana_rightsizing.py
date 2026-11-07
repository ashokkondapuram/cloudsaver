"""Read-only Kubernetes workload rightsizing via Grafana → Mimir (advisory)."""
from __future__ import annotations

import math
import os
import re
import statistics
from datetime import datetime, timedelta, timezone

import httpx

from app.collectors.observability import AUTH_KINDS, FORBIDDEN_HEADERS, HEADER, SECRET_REF, SourceError, check_url, _match

POLICY_VERSION = 'grafana-k8s-rightsizing-v1'
DEFAULT_WINDOW_DAYS = 14
STEP_SECONDS = 300
MAX_CLUSTERS = 20
MAX_ITEMS = 500
MAX_QUERY_LENGTH = 2000
DS_UID = r'[A-Za-z0-9_-]{3,64}'
LABEL = r'[A-Za-z_][A-Za-z0-9_.]{0,79}'
CLUSTER_VALUE = r'[A-Za-z0-9_.:/-]{1,120}'


def validate_connector(raw, tenant):
    if not isinstance(raw, dict):
        raise ValueError('Connector details are required.')
    allowed = {'name', 'kind', 'base_url', 'auth_kind', 'secret_ref', 'header_name', 'mimir_datasource_uid',
               'cluster_label', 'cluster_values', 'org_id', 'schedule'}
    extra = set(raw) - allowed
    if extra:
        raise ValueError('Remove unsupported connector fields: ' + ', '.join(sorted(extra)) + '.')
    name = str(raw.get('name', '')).strip()
    if not 1 <= len(name) <= 80:
        raise ValueError('Enter a connector name of 1–80 characters.')
    if raw.get('kind') != 'grafana_mimir':
        raise ValueError('Choose connector kind grafana_mimir for Grafana rightsizing.')
    base = str(raw.get('base_url', '')).strip()
    base = base if base.endswith('/') else base + '/'
    check_url(base, resolve=False)
    auth = raw.get('auth_kind', 'bearer_env')
    if auth not in AUTH_KINDS:
        raise ValueError('Choose a supported authentication method.')
    if auth not in ('none', 'bearer_env', 'header_env'):
        raise ValueError('Grafana rightsizing supports bearer_env, header_env or none.')
    uid = raw.get('mimir_datasource_uid')
    if not _match(DS_UID, uid):
        raise ValueError('Enter the Mimir datasource UID from Grafana.')
    cluster_label = raw.get('cluster_label', 'cluster')
    if not _match(LABEL, cluster_label):
        raise ValueError('Cluster label must be a valid Prometheus label name.')
    values = raw.get('cluster_values') or []
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_CLUSTERS:
        raise ValueError(f'Add 1–{MAX_CLUSTERS} cluster identifiers to analyze.')
    if any(not _match(CLUSTER_VALUE, str(v)) for v in values):
        raise ValueError('Each cluster value must be 1–120 characters.')
    org_id = raw.get('org_id')
    if org_id is not None and (type(org_id) is not int or not 1 <= org_id <= 999999):
        raise ValueError('org_id must be a positive integer when set.')
    schedule = raw.get('schedule', 'manual')
    if schedule not in ('manual',):
        raise ValueError('Grafana rightsizing connectors use a manual schedule.')
    item = dict(name=name, kind='grafana_mimir', base_url=base, auth_kind=auth, secret_ref=None, header_name=None,
                mimir_datasource_uid=uid, cluster_label=cluster_label, cluster_values=sorted(set(str(v) for v in values)),
                org_id=org_id, schedule='manual', queries=[], services=[], mappings={}, thresholds={},
                trace_window_hours=1, aws_account_id=None, gcp_project_id=None)
    if auth in ('bearer_env', 'header_env'):
        if not _match(SECRET_REF, raw.get('secret_ref')):
            raise ValueError('Secret reference must name CLOUDSAVER_OBSERVABILITY_SECRET_.')
        item['secret_ref'] = raw['secret_ref']
    if auth == 'header_env':
        if not _match(HEADER, raw.get('header_name')) or raw['header_name'].lower() in FORBIDDEN_HEADERS:
            raise ValueError('Enter a valid header name for the secret.')
        item['header_name'] = raw['header_name']
    return item


def _secret(config):
    ref = config.get('secret_ref')
    if not ref:
        return None
    value = os.getenv(ref, '').strip()
    if not value:
        raise SourceError('secret_unavailable')
    return value


def _headers(config):
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    auth = config.get('auth_kind', 'none')
    if auth == 'bearer_env':
        token = _secret(config)
        headers['Authorization'] = 'Bearer ' + token
    elif auth == 'header_env':
        headers[config['header_name']] = _secret(config)
    if config.get('org_id') is not None:
        headers['X-Grafana-Org-Id'] = str(config['org_id'])
    return headers


def _cluster_matcher(config, cluster: str | None):
    label = config['cluster_label']
    if cluster:
        return f'{label}="{cluster}"'
    joined = '|'.join(re.escape(v) for v in config['cluster_values'])
    return f'{label}=~"{joined}"'


def _p95(values: list[float]) -> float | None:
    finite = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    if len(finite) < 2:
        return max(finite) if finite else None
    finite.sort()
    index = max(0, min(len(finite) - 1, math.ceil(0.95 * len(finite)) - 1))
    return finite[index]


def _ceil_cpu_cores(cores: float) -> float:
    millicores = math.ceil(cores * 1000 / 10) * 10
    return millicores / 1000


def _ceil_memory_bytes(value: float) -> float:
    mib = 1024**2
    return math.ceil(value / mib / 16) * 16 * mib


class GrafanaClient:
    def __init__(self, config, *, timeout=60):
        self.config = config
        self.base = config['base_url'].rstrip('/') + '/'
        self.uid = config['mimir_datasource_uid']
        self.timeout = timeout

    def _client(self):
        return httpx.Client(base_url=self.base, headers=_headers(self.config), timeout=self.timeout, follow_redirects=False)

    def test(self):
        with self._client() as client:
            response = client.get(f'api/datasources/uid/{self.uid}')
            if response.status_code in (401, 403):
                raise SourceError('grafana_auth')
            if response.status_code != 200:
                raise SourceError('datasource_unreachable')
            body = response.json()
            if body.get('type') not in ('prometheus', 'loki', 'alertmanager', 'grafana'):
                raise SourceError('datasource_type')
            return dict(ok=True, name=body.get('name'), type=body.get('type'), uid=self.uid)

    def query_range(self, expr: str, start: datetime, end: datetime, *, step=STEP_SECONDS):
        if len(expr) > MAX_QUERY_LENGTH:
            raise SourceError('query_too_long')
        payload = {'queries': [dict(refId='A', datasource=dict(type='prometheus', uid=self.uid), expr=expr,
                                   intervalMs=step * 1000, maxDataPoints=11000, range=True)],
                     'from': str(int(start.timestamp() * 1000)), 'to': str(int(end.timestamp() * 1000))}
        with self._client() as client:
            response = client.post('api/ds/query', json=payload)
            if response.status_code in (401, 403):
                raise SourceError('grafana_auth')
            if response.status_code != 200:
                raise SourceError('query_failed')
            return response.json()


def _series_from_frames(payload) -> dict[tuple, list[float]]:
    """Map (namespace,pod,container) -> usage samples."""
    series: dict[tuple, list[float]] = {}
    results = (payload or {}).get('results') or {}
    for block in results.values():
        for frame in (block or {}).get('frames') or []:
            schema = (frame.get('schema') or {}).get('fields') or []
            values = (frame.get('data') or {}).get('values') or []
            if len(values) < 2:
                continue
            labels = (schema[1] if len(schema) > 1 else {}).get('labels') or {}
            ns, pod, container = labels.get('namespace', ''), labels.get('pod', ''), labels.get('container', '')
            if not container or container == 'POD':
                continue
            key = (ns, pod, container)
            for point in values[1]:
                if point is None:
                    continue
                series.setdefault(key, []).append(float(point))
    return series


def _requests_from_frames(payload, resource: str) -> dict[tuple, float]:
    out: dict[tuple, float] = {}
    results = (payload or {}).get('results') or {}
    for block in results.values():
        for frame in (block.get('frames') if block else []) or []:
            schema = (frame.get('schema') or {}).get('fields') or []
            values = (frame.get('data') or {}).get('values') or []
            if not values:
                continue
            labels = (schema[-1] if schema else {}).get('labels') or {}
            if labels.get('resource') != resource:
                continue
            ns, pod, container = labels.get('namespace', ''), labels.get('pod', ''), labels.get('container', '')
            if not container or container == 'POD':
                continue
            val = values[-1][-1] if values[-1] else None
            if val is None:
                continue
            out[(ns, pod, container)] = float(val)
    return out


def run_rightsizing(config, *, cluster: str | None = None, window_days: int = DEFAULT_WINDOW_DAYS):
    if cluster and cluster not in config['cluster_values']:
        raise ValueError('Choose a cluster value configured on the connector.')
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=window_days)
    matcher = _cluster_matcher(config, cluster)
    cpu_expr = f'sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{{{matcher},container!="",container!="POD"}}[5m]))'
    mem_expr = f'sum by (namespace, pod, container) (container_memory_working_set_bytes{{{matcher},container!="",container!="POD"}})'
    cpu_requests = f'kube_pod_container_resource_requests{{{matcher},resource="cpu",container!="",container!="POD"}}'
    mem_requests = f'kube_pod_container_resource_requests{{{matcher},resource="memory",container!="",container!="POD"}}'
    client = GrafanaClient(config)
    client.test()
    cpu_usage = _series_from_frames(client.query_range(cpu_expr, start, end))
    mem_usage = _series_from_frames(client.query_range(mem_expr, start, end))
    cpu_req = _requests_from_frames(client.query_range(cpu_requests, end, end, step=STEP_SECONDS), 'cpu')
    mem_req = _requests_from_frames(client.query_range(mem_requests, end, end, step=STEP_SECONDS), 'memory')
    keys = sorted(set(cpu_usage) | set(mem_usage) | set(cpu_req) | set(mem_req))[:MAX_ITEMS]
    items = []
    for ns, pod, container in keys:
        cpu_p95 = _p95(cpu_usage.get((ns, pod, container), []))
        mem_p95 = _p95(mem_usage.get((ns, pod, container), []))
        current_cpu = cpu_req.get((ns, pod, container))
        current_mem = mem_req.get((ns, pod, container))
        suggested_cpu = _ceil_cpu_cores(cpu_p95 * 1.2) if cpu_p95 is not None else None
        suggested_mem = _ceil_memory_bytes(mem_p95 * 1.2) if mem_p95 is not None else None
        direction = 'unchanged'
        if suggested_cpu and current_cpu and current_cpu > 0:
            ratio = abs(suggested_cpu - current_cpu) / current_cpu
            if ratio >= 0.10:
                direction = 'decrease' if suggested_cpu < current_cpu else 'increase'
        items.append(dict(namespace=ns, pod=pod, container=container, cluster=cluster or ','.join(config['cluster_values']),
                          current_cpu_request=current_cpu, current_memory_request=current_mem,
                          suggested_cpu_request=suggested_cpu, suggested_memory_request=suggested_mem,
                          cpu_p95=cpu_p95, memory_p95=mem_p95, memory_p99=_p95(mem_usage.get((ns, pod, container), [])),
                          recommendation_direction=direction, confidence='advisory',
                          coverage_ratio=min(1.0, len(cpu_usage.get((ns, pod, container), [])) / max(1, window_days * 24 * 12)),
                          needs_review=direction == 'decrease' and (cpu_p95 or 0) <= 0,
                          rationale='Based on p95 usage with 20% headroom (policy ' + POLICY_VERSION + ').'))
    return dict(policy_version=POLICY_VERSION, queried_at=end.isoformat(), window_days=window_days,
                window_start=start.isoformat(), window_end=end.isoformat(), cluster=cluster, items=items,
                item_count=len(items), truncated=len(keys) >= MAX_ITEMS)


def probe(config):
    try:
        return GrafanaClient(config).test()
    except SourceError as error:
        return dict(ok=False, error_code=error.code)
