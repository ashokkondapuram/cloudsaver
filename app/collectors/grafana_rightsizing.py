"""Read-only Kubernetes workload rightsizing via Grafana → Mimir (advisory)."""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.collectors.grafana_k8s_policy import (
    COVERAGE_MIN, coverage_blocks, cpu_overrequest_detected, cpu_safety_blocks, memory_overrequest_detected,
    memory_safety_blocks, scan_aligned_cpu_target, scan_aligned_memory_target,
)
from app.collectors.grafana_telemetry import (
    CONTAINER_KEY, OWNER_KEY, GrafanaSeriesError, coverage_ratio, instant_label_rows, requests_from_frames,
    series_from_frames, validate_query_payload, values_for_percentile,
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


PUBLIC_ERROR_CODES = {
    'secret_unavailable': ('GRAFANA_SECRET_UNAVAILABLE', False),
    'grafana_auth': ('GRAFANA_AUTH_FAILED', False),
    'datasource_unreachable': ('GRAFANA_DATASOURCE_UNREACHABLE', True),
    'datasource_type': ('GRAFANA_DATASOURCE_INVALID', False),
    'query_too_long': ('GRAFANA_QUERY_TOO_LONG', False),
    'query_failed': ('GRAFANA_QUERY_FAILED', True),
}


def map_rightsizing_error(error: Exception, *, correlation_id: str) -> dict:
    if isinstance(error, SourceError):
        code, retryable = PUBLIC_ERROR_CODES.get(error.code, ('GRAFANA_QUERY_FAILED', True))
    elif isinstance(error, GrafanaSeriesError):
        code, retryable = error.code, error.code in ('GRAFANA_QUERY_FAILED', 'GRAFANA_DATASOURCE_UNREACHABLE')
    elif isinstance(error, ValueError):
        code, retryable = 'GRAFANA_POLICY_VALIDATION_FAILED', False
    else:
        code, retryable = 'GRAFANA_QUERY_FAILED', True
    return dict(error_code=code, retryable=retryable, correlation_id=correlation_id)


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
            body = response.json()
            validate_query_payload(body)
            return body


def _p95_points(points: list[dict]) -> float | None:
    return _percentile(values_for_percentile(points), 0.95)


def _p99_points(points: list[dict]) -> float | None:
    return _percentile(values_for_percentile(points), 0.99)


def _coverage_blocks(points: list[dict], *, start: datetime, end: datetime, window_days: int) -> tuple[float | None, list[str]]:
    ratio, gap = coverage_ratio(points, window_start=start, window_end=end, window_days=window_days, now=end)
    blocks = coverage_blocks(ratio)
    if gap:
        blocks = sorted(set(blocks + ['INSUFFICIENT_TELEMETRY_COVERAGE']))
    return ratio, blocks


def _build_workload_owners(config, client: GrafanaClient, matcher: str, *, cluster: str) -> dict[OWNER_KEY, tuple[str, str]]:
    """Map (cluster, namespace, pod) -> (workload_kind, workload_name)."""
    label = config['cluster_label']
    owners: dict[OWNER_KEY, tuple[str, str]] = {}
    rs_to_deploy: dict[tuple, str] = {}
    now = datetime.now(timezone.utc)
    pod_owner = client.query_range(f'kube_pod_owner{{{matcher}}}', now, now)
    rs_owner = client.query_range(f'kube_replicaset_owner{{{matcher},owner_kind="Deployment"}}', now, now)
    for row in instant_label_rows(rs_owner, cluster=cluster, cluster_label=label):
        cl = row.get('cluster', cluster)
        ns, rs = row.get('namespace', ''), row.get('replicaset', row.get('owner_name', ''))
        deploy = row.get('owner_name', '')
        if cl and ns and rs and deploy:
            rs_to_deploy[(cl, ns, rs)] = deploy
    for row in instant_label_rows(pod_owner, cluster=cluster, cluster_label=label):
        cl = row.get('cluster', cluster)
        ns, pod = row.get('namespace', ''), row.get('pod', '')
        kind, name = row.get('owner_kind', ''), row.get('owner_name', '')
        if not cl or not ns or not pod:
            continue
        owner_key = (cl, ns, pod)
        if kind == 'ReplicaSet' and (cl, ns, name) in rs_to_deploy:
            owners[owner_key] = ('Deployment', rs_to_deploy[(cl, ns, name)])
        elif kind in ('StatefulSet', 'DaemonSet', 'Job', 'CronJob') and name:
            owners[owner_key] = (kind, name)
        elif kind and name:
            owners[owner_key] = (kind, name)
        else:
            owners[owner_key] = ('Pod', pod)
    return owners


def _hpa_workloads(config, client: GrafanaClient, matcher: str, *, cluster: str) -> dict:
    label = config['cluster_label']
    targets: set[tuple] = set()
    expr = f'kube_horizontalpodautoscaler_info{{{matcher}}}'
    try:
        payload = client.query_range(expr, datetime.now(timezone.utc), datetime.now(timezone.utc))
    except SourceError:
        return dict(status='unavailable', targets=targets, reason_code='HPA_QUERY_FAILED')
    for row in instant_label_rows(payload, cluster=cluster, cluster_label=label):
        cl = row.get('cluster', cluster)
        ns = row.get('namespace', '')
        kind = row.get('scaletargetref_kind', row.get('target_kind', 'Deployment'))
        name = row.get('scaletargetref_name', row.get('target_name', ''))
        if cl and ns and name:
            targets.add((cl, ns, kind or 'Deployment', name))
    return dict(status='observed', targets=targets, reason_code=None)


def _run_rightsizing_for_cluster(config, *, cluster: str, window_days: int):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=window_days)
    matcher = _cluster_matcher(config, cluster)
    label = config['cluster_label']
    cpu_expr = f'sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{{{matcher},container!="",container!="POD"}}[5m]))'
    mem_expr = f'sum by (namespace, pod, container) (container_memory_working_set_bytes{{{matcher},container!="",container!="POD"}})'
    cpu_requests = f'kube_pod_container_resource_requests{{{matcher},resource="cpu",container!="",container!="POD"}}'
    mem_requests = f'kube_pod_container_resource_requests{{{matcher},resource="memory",container!="",container!="POD"}}'
    throttle_expr = f'sum by (namespace, pod, container) (rate(container_cpu_cfs_throttled_periods_total{{{matcher},container!="",container!="POD"}}[5m])) / sum by (namespace, pod, container) (rate(container_cpu_cfs_periods_total{{{matcher},container!="",container!="POD"}}[5m]))'
    oom_expr = f'max by (namespace, pod, container) (kube_pod_container_status_last_terminated_reason{{{matcher},reason="OOMKilled",container!="",container!="POD"}})'
    client = GrafanaClient(config)
    client.test()
    owners = _build_workload_owners(config, client, matcher, cluster=cluster)
    hpa_state = _hpa_workloads(config, client, matcher, cluster=cluster)
    hpa_targets = hpa_state['targets']
    cpu_usage = series_from_frames(client.query_range(cpu_expr, start, end), cluster=cluster, cluster_label=label)
    mem_usage = series_from_frames(client.query_range(mem_expr, start, end), cluster=cluster, cluster_label=label)
    throttle_usage = series_from_frames(client.query_range(throttle_expr, start, end), cluster=cluster, cluster_label=label)
    oom_usage = series_from_frames(client.query_range(oom_expr, start, end), cluster=cluster, cluster_label=label)
    cpu_req = requests_from_frames(client.query_range(cpu_requests, end, end, step=STEP_SECONDS), 'cpu', cluster=cluster, cluster_label=label)
    mem_req = requests_from_frames(client.query_range(mem_requests, end, end, step=STEP_SECONDS), 'memory', cluster=cluster, cluster_label=label)
    latency_by_key: dict[CONTAINER_KEY, list[dict]] = {}
    latency_query_failed = False
    if config.get('latency_query'):
        try:
            latency_expr = render_latency_query(config['latency_query'], cluster_matcher=matcher)
            latency_payload = client.query_range(
                latency_expr,
                start,
                end,
                datasource_uid=config.get('latency_datasource_uid') or config['mimir_datasource_uid'],
            )
            latency_by_key = latency_points_from_grafana_frames(
                latency_payload, unit=config.get('latency_unit', 'milliseconds'), cluster=cluster, cluster_label=label,
            )
        except SourceError:
            latency_by_key = {}
            latency_query_failed = True
    slo_latency_target_ms = float(config.get('slo_latency_target_ms') or 100.0)
    all_keys = sorted(set(cpu_usage) | set(mem_usage) | set(cpu_req) | set(mem_req))
    total_item_count = len(all_keys)
    keys = all_keys[:MAX_ITEMS]
    items = []
    for key in keys:
        cl, ns, pod, container = key
        wl_kind, wl_name = owners.get((cl, ns, pod), ('Pod', pod))
        if hpa_state['status'] == 'unavailable':
            hpa_managed = None
        else:
            hpa_managed = (
                (cl, ns, wl_kind, wl_name) in hpa_targets or (cl, ns, 'Deployment', wl_name) in hpa_targets
            )
        cpu_points = cpu_usage.get(key, [])
        mem_points = mem_usage.get(key, [])
        throttle_points = throttle_usage.get(key, [])
        cpu_cov, cpu_cov_blocks = _coverage_blocks(cpu_points, start=start, end=end, window_days=window_days)
        mem_cov, mem_cov_blocks = _coverage_blocks(mem_points, start=start, end=end, window_days=window_days)
        throttle_cov, throttle_cov_blocks = _coverage_blocks(throttle_points, start=start, end=end, window_days=window_days)
        cpu_p95 = _p95_points(cpu_points)
        mem_p95 = _p95_points(mem_points)
        mem_p99 = _p99_points(mem_points)
        throttle_p95 = _p95_points(throttle_points)
        oom_observed = any(p.get('value', 0) > 0 for p in oom_usage.get(key, []) if isinstance(p, dict))
        current_cpu = cpu_req.get(key)
        current_mem = mem_req.get(key)
        suggested_cpu = _ceil_cpu_cores(scan_aligned_cpu_target(cpu_p95)) if cpu_p95 is not None else None
        suggested_mem = _ceil_memory_bytes(scan_aligned_memory_target(mem_p99)) if mem_p99 is not None else None
        latency_points = latency_by_key.get(key, [])
        latency_blocks: list[str] = []
        if config.get('latency_query'):
            if latency_query_failed or not latency_points:
                latency_blocks.append('LATENCY_NOT_OBSERVED')
            else:
                _, lat_blocks = _coverage_blocks(latency_points, start=start, end=end, window_days=window_days)
                latency_blocks.extend(lat_blocks)
        safety = (
            cpu_cov_blocks
            + mem_cov_blocks
            + throttle_cov_blocks
            + cpu_safety_blocks(throttle_p95=throttle_p95, hpa_managed=hpa_managed)
            + memory_safety_blocks(oom_observed=oom_observed, restart_spread=False)
            + latency_blocks
        )
        cpu_detected = cpu_overrequest_detected(current_cpu, cpu_p95)
        mem_detected = memory_overrequest_detected(current_mem, mem_p99)
        mem_coverage_ok = mem_cov is not None and mem_cov >= COVERAGE_MIN and not mem_cov_blocks
        direction = 'unchanged'
        if suggested_cpu and current_cpu and current_cpu > 0:
            ratio = abs(suggested_cpu - current_cpu) / current_cpu
            if ratio >= 0.10:
                direction = 'decrease' if suggested_cpu < current_cpu else 'increase'
        latency_p99 = _p99_points(latency_points) if latency_points else None
        if latency_p99 is not None and config.get('latency_query') and latency_p99 >= slo_latency_target_ms * 0.9:
            safety = sorted(set(safety + ['BLOCKED_BY_TAIL_LATENCY_PROXIMITY']))
        coverage = cpu_cov if cpu_cov is not None else 0.0
        needs_review = bool(safety) or (cpu_cov or 0) < COVERAGE_MIN or (direction == 'decrease' and not (cpu_detected or mem_detected))
        eligible_cpu = cpu_detected and not safety and direction == 'decrease'
        eligible_mem = mem_detected and mem_coverage_ok and not safety and suggested_mem and current_mem and suggested_mem < current_mem
        latency_series = None
        row_latency_basis = None
        if latency_points:
            row_latency_basis = OBSERVABILITY_LATENCY_BASIS
            latency_series = dict(
                window_start=start.isoformat(),
                window_end=end.isoformat(),
                points=latency_points,
                basis=OBSERVABILITY_LATENCY_BASIS,
            )
        item = dict(
            namespace=ns, pod=pod, container=container, workload_kind=wl_kind, workload_name=wl_name,
            cluster=cl,
            current_cpu_request=current_cpu, current_memory_request=current_mem,
            suggested_cpu_request=suggested_cpu, suggested_memory_request=suggested_mem,
            scan_aligned_cpu_request=scan_aligned_cpu_target(cpu_p95),
            scan_aligned_memory_request=scan_aligned_memory_target(mem_p99),
            cpu_p95=cpu_p95, memory_p95=mem_p95, memory_p99=mem_p99, cpu_throttle_p95=throttle_p95,
            hpa_managed=hpa_managed, oom_observed=oom_observed,
            cpu_overrequest_detected=cpu_detected, memory_overrequest_detected=mem_detected,
            recommendation_direction=direction, confidence='advisory' if not safety else 'needs_review',
            coverage_ratio=coverage, memory_coverage_ratio=mem_cov,
            safety_blocks=sorted(set(safety)),
            needs_review=needs_review, patch_eligible=eligible_cpu or eligible_mem,
            rationale='Advisory sizing uses scan-aligned headroom (CPU P95×1.5, memory P99×1.35). '
                      + f'Policy {POLICY_VERSION}.',
        )
        if latency_p99 is not None:
            item['latency_p99_ms'] = latency_p99
        if row_latency_basis is not None:
            item['latency_basis'] = row_latency_basis
        if latency_series is not None:
            item['latency_p99_series'] = latency_series
        items.append(item)
    latency_query_status = None
    if config.get('latency_query'):
        latency_query_status = 'unavailable' if latency_query_failed or not latency_by_key else 'observed'
    truncated = total_item_count > MAX_ITEMS
    return dict(
        policy_version=POLICY_VERSION, queried_at=end.isoformat(), window_days=window_days,
        window_start=start.isoformat(), window_end=end.isoformat(), cluster=cluster, items=items,
        item_count=len(items), total_item_count=total_item_count, returned_item_count=len(items),
        omitted_item_count=max(0, total_item_count - len(items)), truncated=truncated,
        latency_query_status=latency_query_status, hpa_status=hpa_state['status'],
    )


def run_rightsizing(config, *, cluster: str | None = None, window_days: int = DEFAULT_WINDOW_DAYS):
    if cluster and cluster not in config['cluster_values']:
        raise ValueError('Choose a cluster value configured on the connector.')
    clusters = [cluster] if cluster else list(config['cluster_values'])
    combined: list[dict] = []
    meta: dict | None = None
    for cl in clusters:
        chunk = _run_rightsizing_for_cluster(config, cluster=cl, window_days=window_days)
        combined.extend(chunk['items'])
        meta = chunk
    total_item_count = len(combined)
    items = combined[:MAX_ITEMS]
    omitted = max(0, total_item_count - len(items))
    return dict(
        **{k: v for k, v in (meta or {}).items() if k not in ('items', 'item_count', 'cluster', 'total_item_count', 'returned_item_count', 'omitted_item_count', 'truncated')},
        cluster=cluster,
        items=items,
        item_count=len(items),
        total_item_count=total_item_count,
        returned_item_count=len(items),
        omitted_item_count=omitted,
        truncated=total_item_count > MAX_ITEMS,
    )


def probe(config):
    try:
        return GrafanaClient(config).test()
    except SourceError as error:
        return dict(ok=False, error_code=error.code)
