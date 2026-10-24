"""Tenant-bound inventory, independently fenced Prometheus and allocation readers."""
import json
import math
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from app.cloud_http import JSONReader
from app.cloud_scope import NAME, POD_NAME, matches
from app.scanner import ScanError
from app.telemetry_contract import TimeSeriesEvidenceContract, evaluate_series
from app.collectors.provenance import digest, entry

VERSION = 'kubernetes-federation-2026-10-24.1'
RESOURCES = (
    ('/api/v1/pods', 'Pod'), ('/api/v1/nodes', 'Node'), ('/api/v1/namespaces', 'Namespace'),
    ('/apis/apps/v1/deployments', 'Deployment'), ('/apis/apps/v1/statefulsets', 'StatefulSet'),
    ('/apis/apps/v1/daemonsets', 'DaemonSet'), ('/apis/apps/v1/replicasets', 'ReplicaSet'),
    ('/apis/batch/v1/jobs','Job'),
    ('/apis/batch/v1/cronjobs', 'CronJob'), ('/apis/autoscaling/v2/horizontalpodautoscalers', 'HorizontalPodAutoscaler'),
    ('/apis/policy/v1/poddisruptionbudgets', 'PodDisruptionBudget'),
    ('/api/v1/persistentvolumeclaims', 'PersistentVolumeClaim'), ('/api/v1/persistentvolumes', 'PersistentVolume'),
    ('/apis/storage.k8s.io/v1/storageclasses', 'StorageClass'), ('/api/v1/services', 'Service'),
    ('/apis/discovery.k8s.io/v1/endpointslices', 'EndpointSlice'),
)


def binding(tenant_id, cluster_id):
    if tenant_id is None:return None
    try:
        values = json.loads(os.getenv('CLOUDSAVER_KUBERNETES_BINDINGS', '[]'))
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError()
        selected = [v for v in values if v.get('tenant_id') == tenant_id and v.get('cluster_id') == cluster_id]
        if len(selected) > 1:
            raise ValueError()
        if not selected:
            return None
        value = selected[0]
        allowed = {'tenant_id', 'cluster_id', 'api_url', 'api_token_env', 'opencost_url', 'opencost_token_env',
                   'telemetry_backend', 'region', 'role_arn', 'service_account', 'hosting_provider'}
        if set(value) - allowed or value.get('telemetry_backend', 'prometheus_http') not in ('prometheus_http', 'azure_amp', 'aws_amp_sigv4', 'gcp_gmp'):
            raise ValueError()
        for field in ('api_url', 'opencost_url'):
            if value.get(field):
                url = urlsplit(value[field])
                if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError()
        if not value.get('api_url'):
            raise ValueError()
        for field in ('api_token_env', 'opencost_token_env'):
            if value.get(field) and not matches(r'CLOUDSAVER_K8S_[A-Z0-9_]{1,80}', value[field]):
                raise ValueError()
        if not value.get('api_token_env'):
            raise ValueError()
        if value.get('hosting_provider') not in (None, 'azure', 'aws', 'gcp', 'self_hosted'):
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise ScanError('Invalid operator Kubernetes binding; no inventory was saved') from None


def inventory(reader, base):
    """Core inventory is mandatory; denied secondary APIs retain explicit source failures."""
    objects, sources = {}, []
    for path, kind in RESOURCES:
        rows = []
        try:
            token, seen = None, set()
            for _ in range(200):
                page = reader.get(base.rstrip('/') + path, {'limit': 500, **({'continue': token} if token else {})})
                batch = page.get('items')
                if not isinstance(batch, list) or page.get('kind') == 'Status' or page.get('code', 200) >= 400:
                    raise ScanError('Invalid Kubernetes inventory page')
                for row in batch:
                    meta = row.get('metadata', {})
                    if row.get('kind', kind) != kind or not matches(POD_NAME, meta.get('name')) or not isinstance(meta.get('uid'), str):
                        raise ScanError('Invalid Kubernetes object identity')
                    if kind not in ('Node', 'Namespace', 'PersistentVolume', 'StorageClass') and not matches(NAME, meta.get('namespace')):
                        raise ScanError('Invalid Kubernetes namespace identity')
                    rows.append(row)
                if len(rows) > 20000:
                    raise ScanError('Kubernetes inventory resource limit exceeded')
                token = (page.get('metadata') or {}).get('continue')
                if not token:
                    break
                if not isinstance(token, str) or len(token) > 10000 or token in seen:
                    raise ScanError('Invalid Kubernetes continuation')
                seen.add(token)
            else:
                raise ScanError('Kubernetes pagination limit exceeded')
            identities = [(r['metadata'].get('namespace'), r['metadata']['name']) for r in rows]
            if len(set(identities)) != len(identities):
                raise ScanError('Repeated Kubernetes object identity')
            objects[kind] = rows
            sources.append(entry('kubernetes_api:' + kind, 'kubernetes_api', end=datetime.now(timezone.utc).isoformat(), digest=digest(rows)))
        except Exception:
            if kind in ('Pod', 'Node', 'Namespace'):
                raise ScanError('Primary Kubernetes inventory is unavailable; no snapshot was saved') from None
            objects[kind] = None
            sources.append(entry('kubernetes_api:' + kind, 'kubernetes_api', status='unavailable', reason='api_unavailable_or_incomplete'))
    return objects, sources


def queries(cluster):
    selector = 'cluster=' + json.dumps(cluster) + ',container!="",container!="POD"'
    aggregate = 'sum by (cluster,namespace,pod,container) '
    c = '{' + selector + '}'
    image = '{' + selector + ',image!=""}'
    return {
        'cpu': (aggregate + '(rate(container_cpu_usage_seconds_total' + image + '[5m]))', 'container', False),
        'memory': ('max by (cluster,namespace,pod,container) (container_memory_working_set_bytes' + image + ')', 'container', False),
        'throttling': (aggregate + '(rate(container_cpu_cfs_throttled_periods_total' + c + '[5m])) / ' + aggregate + '(rate(container_cpu_cfs_periods_total' + c + '[5m]))', 'container', True),
        'cpu_request': ('max by (cluster,namespace,pod,container) (kube_pod_container_resource_requests{' + selector + ',resource="cpu",unit="core"})', 'container', False),
        'memory_request': ('max by (cluster,namespace,pod,container) (kube_pod_container_resource_requests{' + selector + ',resource="memory",unit="byte"})', 'container', False),
        # A last-termination reason alone cannot prove zero OOMs across a whole window.
        'oom': ('max by (cluster,namespace,pod,container) (kube_pod_container_status_last_terminated_reason{' + selector + ',reason="OOMKilled"})', 'container', True),
        'restarts': ('max by (cluster,namespace,pod,container) (kube_pod_container_status_restarts_total' + c + ')', 'container', False),
        'network': ('sum by (cluster,namespace,pod) (rate(container_network_receive_bytes_total{cluster=' + json.dumps(cluster) + ',interface!="lo"}[5m]) + rate(container_network_transmit_bytes_total{cluster=' + json.dumps(cluster) + ',interface!="lo"}[5m]))', 'pod', False),
        'pvc_occupancy': ('max by (cluster,namespace,persistentvolumeclaim) (kubelet_volume_stats_used_bytes{cluster=' + json.dumps(cluster) + '}) / max by (cluster,namespace,persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes{cluster=' + json.dumps(cluster) + '})', 'pvc', True),
        'pvc_mounts': ('count by (cluster,namespace,persistentvolumeclaim) (kube_pod_spec_volumes_persistentvolumeclaims_info{cluster=' + json.dumps(cluster) + '})', 'pvc', False),
        'service_endpoints': ('sum by (cluster,namespace,service) (kube_endpoint_address_available{cluster=' + json.dumps(cluster) + '})', 'service', False),
    }


def matrix(payload, cluster, metric, kind, ratio, start, end, now):
    if payload.get('status') != 'success' or payload.get('warnings') or payload.get('infos'):
        raise ScanError('Partial Prometheus response')
    data = payload.get('data', {})
    if data.get('resultType') != 'matrix' or not isinstance(data.get('result'), list) or len(data['result']) > 20000:
        raise ScanError('Invalid Prometheus matrix')
    result = {}
    for row in data['result']:
        labels = row.get('metric') or {}
        fields = {'container': ('namespace', 'pod', 'container'), 'pod': ('namespace', 'pod'), 'pvc': ('namespace', 'persistentvolumeclaim'), 'service': ('namespace', 'service')}[kind]
        key = tuple(labels.get(field) for field in fields)
        if labels.get('cluster') != cluster or any(not matches(POD_NAME if field == 'pod' else NAME, val) for field, val in zip(fields, key)) or key in result:
            raise ScanError('Ambiguous or foreign Prometheus identity')
        points = []
        for stamp, raw in row.get('values', []):
            if type(raw) is bool:raise ScanError('Invalid metric value type')
            value = float(raw)
            if not math.isfinite(value) or value < 0 or ratio and value > 1:
                raise ScanError('Invalid metric sample')
            points.append({'at': datetime.fromtimestamp(float(stamp), timezone.utc).isoformat(), 'value': value})
        values = dict(window_start=start.isoformat(), window_end=end.isoformat(), points=points)
        # Validate timestamps and coverage once, then derive all peaks from the same valid sample set.
        check=evaluate_series(values,TimeSeriesEvidenceContract(metric,'P95'),now=now,require_resource_age=False)
        ordered=sorted(p['value'] for p in points)
        stats={'p95':check.observed_value,'p99':ordered[math.ceil(.99*len(ordered))-1] if check.is_sufficient else None,
               'maximum':ordered[-1] if check.is_sufficient else None}
        stats.update(sufficient=check.is_sufficient, minimum=ordered[0] if ordered else None,
                     window_days=30, window_start=start.isoformat(), window_end=end.isoformat(),
                     coverage_ratio=check.coverage_ratio, valid_samples=check.valid_samples, expected_samples=check.expected_samples,
                     max_gap_minutes=check.max_observed_gap_minutes, gap_reason=check.gap_reason,
                     evidence_digest=digest(points))
        result[key] = stats
    return result


def telemetry(reader, base, cluster, now):
    end = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % 5)
    start = end-timedelta(days=30)
    metrics, sources = {}, []
    failures=0
    for name, (query, kind, ratio) in queries(cluster).items():
        if failures>=3:
            metrics[name]={}
            sources.append(entry('prometheus:'+name,'prometheus_range_api',status='unavailable',reason='source_circuit_open_for_scan'))
            continue
        try:
            data = reader.get(base.rstrip('/') + '/api/v1/query_range', {'query': query, 'start': int(start.timestamp())+300, 'end': int(end.timestamp()), 'step': 300, 'timeout': '30s'})
            metrics[name] = matrix(data, cluster, name, kind, ratio, start, end, now)
            failures=0
            values = list(metrics[name].values())
            sources.append(entry('prometheus:' + name, 'prometheus_range_api', start=start.isoformat(), end=end.isoformat(), now=now,
                                 status='available' if values and all(v['sufficient'] for v in values) else 'insufficient',
                                 valid_samples=sum(v['valid_samples'] for v in values), expected_samples=8640*len(values), digest=digest(metrics[name])))
        except Exception:
            failures+=1
            metrics[name] = {}
            sources.append(entry('prometheus:' + name, 'prometheus_range_api', status='unavailable', reason='metric_unavailable_invalid_or_ambiguous'))
    return metrics, sources


def token_reader(env):
    token = os.getenv(env or '')
    if not token:
        raise ScanError('Configured Kubernetes source credential is unavailable')
    return JSONReader(token=token,timeout_seconds=15)
