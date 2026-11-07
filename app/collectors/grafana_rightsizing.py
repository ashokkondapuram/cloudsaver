"""Read-only Kubernetes workload rightsizing via Grafana → Mimir (advisory)."""
from __future__ import annotations

import math
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx

from app.collectors.grafana_k8s_policy import (
    COVERAGE_MIN, coverage_blocks, cpu_overrequest_detected, cpu_safety_blocks, memory_overrequest_detected,
    memory_safety_blocks, scan_aligned_cpu_target, scan_aligned_memory_target,
)
from app.collectors.observability import AUTH_KINDS, FORBIDDEN_HEADERS, HEADER, SECRET_REF, SourceError, check_url, _match
from app.kubernetes_latency_evidence import (
    OBSERVABILITY_LATENCY_BASIS, latency_points_from_grafana_frames, render_latency_query, validate_latency_query,
    validate_latency_unit,
)

POLICY_VERSION = 'grafana-k8s-rightsizing-v2'
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
               'latency_datasource_uid', 'latency_query', 'latency_unit', 'slo_latency_target_ms',
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
    latency_query = validate_latency_query(raw.get('latency_query'))
    latency_uid = raw.get('latency_datasource_uid')
    if latency_uid is not None:
        if not _match(DS_UID, latency_uid):
            raise ValueError('Enter a valid datasource UID for latency queries.')
    if latency_uid and not latency_query:
        raise ValueError('Add a latency_query when latency_datasource_uid is set.')
    if latency_query and not latency_uid:
        latency_uid = uid
    latency_unit = validate_latency_unit(raw.get('latency_unit'))
    slo_target = raw.get('slo_latency_target_ms', 100.0)
    if type(slo_target) not in (int, float) or not 1 <= slo_target <= 600_000:
        raise ValueError('slo_latency_target_ms must be between 1 and 600000 when set.')
    item = dict(name=name, kind='grafana_mimir', base_url=base, auth_kind=auth, secret_ref=None, header_name=None,
                mimir_datasource_uid=uid, latency_datasource_uid=latency_uid, latency_query=latency_query,
                latency_unit=latency_unit, slo_latency_target_ms=float(slo_target),
                cluster_label=cluster_label, cluster_values=sorted(set(str(v) for v in values)),
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


def _percentile(values: list[float], pct: float) -> float | None:
    finite = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    if not finite:
        return None
    if len(finite) == 1:
        return finite[0]
    finite.sort()
    index = max(0, min(len(finite) - 1, math.ceil(pct * len(finite)) - 1))
    return finite[index]


def _p95(values: list[float]) -> float | None:
    return _percentile(values, 0.95)


def _p99(values: list[float]) -> float | None:
    return _percentile(values, 0.99)


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

    def query_range(self, expr: str, start: datetime, end: datetime, *, step=STEP_SECONDS, datasource_uid: str | None = None):
        if len(expr) > MAX_QUERY_LENGTH:
            raise SourceError('query_too_long')
        uid = datasource_uid or self.uid
        payload = {'queries': [dict(refId='A', datasource=dict(type='prometheus', uid=uid), expr=expr,
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


def _instant_label_rows(payload) -> list[dict]:
    rows = []
    for block in ((payload or {}).get('results') or {}).values():
        for frame in (block or {}).get('frames') or []:
            schema = (frame.get('schema') or {}).get('fields') or []
            values = (frame.get('data') or {}).get('values') or []
            if not values:
                continue
            label_field = schema[-1] if schema else {}
            labels = label_field.get('labels') or {}
            val = values[-1][-1] if values[-1] else None
            rows.append(dict(labels, value=val))
    return rows


def _build_workload_owners(config, client: GrafanaClient, matcher: str) -> dict[tuple, tuple[str, str]]:
    """Map (namespace, pod) -> (workload_kind, workload_name)."""
    owners: dict[tuple, tuple[str, str]] = {}
    rs_to_deploy: dict[tuple, str] = {}
    pod_owner = client.query_range(f'kube_pod_owner{{{matcher}}}', datetime.now(timezone.utc), datetime.now(timezone.utc))
    rs_owner = client.query_range(f'kube_replicaset_owner{{{matcher},owner_kind="Deployment"}}', datetime.now(timezone.utc), datetime.now(timezone.utc))
    for row in _instant_label_rows(rs_owner):
        ns, rs = row.get('namespace', ''), row.get('replicaset', row.get('owner_name', ''))
        deploy = row.get('owner_name', '')
        if ns and rs and deploy:
            rs_to_deploy[(ns, rs)] = deploy
    for row in _instant_label_rows(pod_owner):
        ns, pod = row.get('namespace', ''), row.get('pod', '')
        kind, name = row.get('owner_kind', ''), row.get('owner_name', '')
        if not ns or not pod:
            continue
        if kind == 'ReplicaSet' and (ns, name) in rs_to_deploy:
            owners[(ns, pod)] = ('Deployment', rs_to_deploy[(ns, name)])
        elif kind in ('StatefulSet', 'DaemonSet', 'Job', 'CronJob') and name:
            owners[(ns, pod)] = (kind, name)
        elif kind and name:
            owners[(ns, pod)] = (kind, name)
        else:
            owners[(ns, pod)] = ('Pod', pod)
    return owners


def _hpa_workloads(config, client: GrafanaClient, matcher: str) -> set[tuple]:
    """Set of (namespace, workload_kind, workload_name) with an HPA scale target."""
    targets: set[tuple] = set()
    expr = f'kube_horizontalpodautoscaler_info{{{matcher}}}'
    try:
        payload = client.query_range(expr, datetime.now(timezone.utc), datetime.now(timezone.utc))
    except SourceError:
        return targets
    for row in _instant_label_rows(payload):
        ns = row.get('namespace', '')
        kind = row.get('scaletargetref_kind', row.get('target_kind', 'Deployment'))
        name = row.get('scaletargetref_name', row.get('target_name', ''))
        if ns and name:
            targets.add((ns, kind or 'Deployment', name))
    return targets


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
    throttle_expr = f'sum by (namespace, pod, container) (rate(container_cpu_cfs_throttled_periods_total{{{matcher},container!="",container!="POD"}}[5m])) / sum by (namespace, pod, container) (rate(container_cpu_cfs_periods_total{{{matcher},container!="",container!="POD"}}[5m]))'
    oom_expr = f'max by (namespace, pod, container) (kube_pod_container_status_last_terminated_reason{{{matcher},reason="OOMKilled",container!="",container!="POD"}})'
    client = GrafanaClient(config)
    client.test()
    owners = _build_workload_owners(config, client, matcher)
    hpa_targets = _hpa_workloads(config, client, matcher)
    cpu_usage = _series_from_frames(client.query_range(cpu_expr, start, end))
    mem_usage = _series_from_frames(client.query_range(mem_expr, start, end))
    throttle_usage = _series_from_frames(client.query_range(throttle_expr, start, end))
    oom_usage = _series_from_frames(client.query_range(oom_expr, start, end))
    cpu_req = _requests_from_frames(client.query_range(cpu_requests, end, end, step=STEP_SECONDS), 'cpu')
    mem_req = _requests_from_frames(client.query_range(mem_requests, end, end, step=STEP_SECONDS), 'memory')
    latency_by_key: dict[tuple, list[dict]] = {}
    default_latency_basis = None
    if config.get('latency_query'):
        try:
            latency_expr = render_latency_query(config['latency_query'], cluster_matcher=matcher)
            latency_payload = client.query_range(
                latency_expr,
                start,
                end,
                datasource_uid=config.get('latency_datasource_uid') or config['mimir_datasource_uid'],
            )
            latency_by_key = latency_points_from_grafana_frames(latency_payload, unit=config.get('latency_unit', 'milliseconds'))
            if latency_by_key:
                default_latency_basis = OBSERVABILITY_LATENCY_BASIS
        except SourceError:
            latency_by_key = {}
    expected_samples = window_days * 24 * 12
    keys = sorted(set(cpu_usage) | set(mem_usage) | set(cpu_req) | set(mem_req))[:MAX_ITEMS]
    items = []
    for ns, pod, container in keys:
        wl_kind, wl_name = owners.get((ns, pod), ('Pod', pod))
        hpa_managed = (ns, wl_kind, wl_name) in hpa_targets or (ns, 'Deployment', wl_name) in hpa_targets
        cpu_samples = cpu_usage.get((ns, pod, container), [])
        mem_samples = mem_usage.get((ns, pod, container), [])
        throttle_samples = throttle_usage.get((ns, pod, container), [])
        cpu_p95 = _p95(cpu_samples)
        mem_p95 = _p95(mem_samples)
        mem_p99 = _p99(mem_samples)
        throttle_p95 = _p95(throttle_samples)
        oom_observed = any(v and v > 0 for v in oom_usage.get((ns, pod, container), []))
        current_cpu = cpu_req.get((ns, pod, container))
        current_mem = mem_req.get((ns, pod, container))
        coverage = min(1.0, len(cpu_samples) / max(1, expected_samples))
        suggested_cpu = _ceil_cpu_cores(scan_aligned_cpu_target(cpu_p95)) if cpu_p95 is not None else None
        suggested_mem = _ceil_memory_bytes(scan_aligned_memory_target(mem_p99)) if mem_p99 is not None else None
        safety = (
            coverage_blocks(coverage)
            + cpu_safety_blocks(throttle_p95=throttle_p95, hpa_managed=hpa_managed)
            + memory_safety_blocks(oom_observed=oom_observed, restart_spread=False)
        )
        cpu_detected = cpu_overrequest_detected(current_cpu, cpu_p95)
        mem_detected = memory_overrequest_detected(current_mem, mem_p99)
        direction = 'unchanged'
        if suggested_cpu and current_cpu and current_cpu > 0:
            ratio = abs(suggested_cpu - current_cpu) / current_cpu
            if ratio >= 0.10:
                direction = 'decrease' if suggested_cpu < current_cpu else 'increase'
        needs_review = bool(safety) or coverage < COVERAGE_MIN or (direction == 'decrease' and not (cpu_detected or mem_detected))
        eligible_cpu = cpu_detected and not safety and direction == 'decrease'
        eligible_mem = mem_detected and not safety and suggested_mem and current_mem and suggested_mem < current_mem
        latency_points = latency_by_key.get((ns, pod, container), [])
        latency_p99 = _p99([p['value'] for p in latency_points]) if latency_points else None
        latency_series = None
        row_latency_basis = default_latency_basis
        if latency_points:
            latency_series = dict(
                window_start=start.isoformat(),
                window_end=end.isoformat(),
                points=latency_points,
                basis=OBSERVABILITY_LATENCY_BASIS,
            )
        item = dict(
            namespace=ns, pod=pod, container=container, workload_kind=wl_kind, workload_name=wl_name,
            cluster=cluster or ','.join(config['cluster_values']),
            current_cpu_request=current_cpu, current_memory_request=current_mem,
            suggested_cpu_request=suggested_cpu, suggested_memory_request=suggested_mem,
            scan_aligned_cpu_request=scan_aligned_cpu_target(cpu_p95),
            scan_aligned_memory_request=scan_aligned_memory_target(mem_p99),
            cpu_p95=cpu_p95, memory_p95=mem_p95, memory_p99=mem_p99, cpu_throttle_p95=throttle_p95,
            hpa_managed=hpa_managed, oom_observed=oom_observed,
            cpu_overrequest_detected=cpu_detected, memory_overrequest_detected=mem_detected,
            recommendation_direction=direction, confidence='advisory' if not safety else 'needs_review',
            coverage_ratio=coverage, safety_blocks=sorted(set(safety)),
            needs_review=needs_review, patch_eligible=eligible_cpu or eligible_mem,
            rationale='Advisory sizing uses scan-aligned headroom (CPU P95×1.5, memory P99×1.35). '
                      + f'Policy {POLICY_VERSION}.',
            latency_p99_ms=latency_p99,
            latency_basis=row_latency_basis,
        )
        if latency_series is not None:
            item['latency_p99_series'] = latency_series
        items.append(item)
    return dict(policy_version=POLICY_VERSION, queried_at=end.isoformat(), window_days=window_days,
                window_start=start.isoformat(), window_end=end.isoformat(), cluster=cluster, items=items,
                item_count=len(items), truncated=len(keys) >= MAX_ITEMS)


def probe(config):
    try:
        return GrafanaClient(config).test()
    except SourceError as error:
        return dict(ok=False, error_code=error.code)
