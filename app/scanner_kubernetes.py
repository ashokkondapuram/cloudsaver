"""Native Prometheus metrics ingestion; averages are never labelled P95 evidence."""
from datetime import datetime, timedelta, timezone
import json
import math
import os

from app.cloud_http import JSONReader
from app.cloud_scope import NAME, POD_NAME, matches, validate_finding_scope
from app.scanner import ScanError
from app.inventory import FindingBatch

WINDOW_HOURS = 336
STEP = 3600


def percentile95(values):
    values = sorted(values)
    return values[math.ceil(0.95 * len(values)) - 1]


def _series(data, cluster, start, end):
    if data.get('status') != 'success' or data.get('warnings') or data.get('infos'):
        raise ScanError('Kubernetes telemetry query was incomplete')
    payload = data.get('data', {})
    if payload.get('resultType') != 'matrix' or not isinstance(payload.get('result'), list):
        raise ScanError('Kubernetes telemetry must be a range matrix')
    result = {}
    if len(payload['result']) > 20000:
        raise ScanError('Kubernetes container series limit exceeded')
    for row in payload['result']:
        labels = row.get('metric', {})
        key = tuple(labels.get(k) for k in ('namespace', 'pod', 'container'))
        if labels.get('cluster') != cluster or any(not matches(pattern, value) for pattern, value in zip((NAME, POD_NAME, NAME), key)):
            raise ScanError('Kubernetes metrics returned an out-of-scope identity')
        if key in result:
            raise ScanError('Duplicate Kubernetes metric series require operator deduplication')
        points = {}
        for point in row.get('values', []):
            try:
                stamp, value = float(point[0]), float(point[1])
                if not math.isfinite(stamp) or not math.isfinite(value) or value < 0:
                    raise ValueError()
                if stamp != int(stamp) or not start <= stamp <= end or (stamp - start) % STEP or stamp in points:
                    raise ValueError()
            except (IndexError, TypeError, ValueError, OverflowError):
                raise ScanError('Kubernetes metrics returned invalid sample values') from None
            points[int(stamp)] = value
        result[key] = points
    return result


def scan_cluster(source, *, reader=None, now=None):
    from app.collectors.kubernetes import binding
    approved = binding(source.get('tenant_id'), source['cluster_id'])
    if approved:
        from app.collectors.federation import scan
        return scan(source, approved, metric_reader=reader, now=now)
    cluster = source['cluster_id']
    now = now or datetime.now(timezone.utc)
    end = int(now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).timestamp())
    start = end - WINDOW_HOURS * STEP
    owned = reader is None
    if owned:
        token = os.getenv(source['bearer_token_env'])
        if not token:
            raise ScanError('Configured Kubernetes telemetry credential is unavailable')
        reader = JSONReader(token=token)
    matcher = 'cluster=' + json.dumps(cluster) + ',container!="",container!="POD"'
    queries = {
        'cpu_request': 'kube_pod_container_resource_requests{' + matcher + ',resource="cpu",unit="core"}',
        'memory_request': 'kube_pod_container_resource_requests{' + matcher + ',resource="memory",unit="byte"}',
        'cpu_usage': 'rate(container_cpu_usage_seconds_total{' + matcher + '}[5m])',
        'memory_usage': 'container_memory_working_set_bytes{' + matcher + '}',
    }
    try:
        series = {key: _series(reader.get(source['prometheus_url'].rstrip('/') + '/api/v1/query_range',
                     {'query': query, 'start': start, 'end': end, 'step': STEP, 'timeout': '45s'}), cluster, start, end)
                  for key, query in queries.items()}
        findings = []
        expected = set(range(start, end + 1, STEP))
        for dimension in ('cpu', 'memory'):
            for key, requests in series[dimension + '_request'].items():
                usage = series[dimension + '_usage'].get(key, {})
                # A full 14-day window is required: new pods, gaps and stale data are unknown.
                if set(requests) != expected or set(usage) != expected:
                    continue
                baseline, p95 = min(requests.values()), percentile95(list(usage.values()))
                if baseline <= 0 or baseline <= p95 * 1.5:
                    continue
                namespace, pod, container = key
                rid = f'k8s://{cluster}/namespaces/{namespace}/pods/{pod}/containers/{container}'
                result = dict(rule_id='K8S_' + dimension.upper() + '_OVERSIZED', cloud_provider='kubernetes',
                    scope_id=cluster, subscription_id=cluster, resource_id=rid, resource_name=container,
                    resource_group=namespace, resource_type='kubernetes.io/Container', severity='MEDIUM',
                    estimated_monthly_waste_usd=None,
                    details=f'{dimension.upper()} request exceeds P95 hourly-sampled usage over 14 days by more than 50%. CPU uses five-minute rates; memory uses working-set samples. Review peaks, limits, SLOs and controller configuration. No node or dollar savings is implied.',
                    evidence=dict(source='Prometheus query_range', dimension=dimension, window_days=14,
                        window_start=datetime.fromtimestamp(start, timezone.utc).isoformat(),
                        window_end=datetime.fromtimestamp(end, timezone.utc).isoformat(), samples=len(expected),
                        step_seconds=STEP, percentile_method='nearest_rank_0.95',
                        minimum_request=baseline, p95_usage=p95,
                        suggested_request_with_50pct_headroom=p95 * 1.5 if p95 > 0 else None,
                        unit='cores' if dimension == 'cpu' else 'bytes'))
                validate_finding_scope(result, {'kubernetes_clusters': [source]})
                findings.append(result)
        inventory = []
        for namespace, pod, container in sorted(set().union(*(set(value) for value in series.values()))):
            inventory.append(dict(cloud_provider='kubernetes', scope_id=cluster, subscription_id=cluster,
                inventory_rule_id='K8S_CPU_OVERSIZED',
                resource_id=f'k8s://{cluster}/namespaces/{namespace}/pods/{pod}/containers/{container}',
                resource_name=container, resource_group=namespace, resource_type='kubernetes.io/Container',
                evidence={'source': 'Prometheus query_range', 'inventory_basis': 'metrics_visible_containers'}))
        return FindingBatch(findings, inventory, basis='metrics_visible_containers')
    except ScanError:
        raise
    except Exception:
        raise ScanError('Kubernetes metrics scan failed; no partial inventory was saved') from None
    finally:
        if owned:
            reader.close()
