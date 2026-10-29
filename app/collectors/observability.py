"""Read-only observability connectors: Prometheus, REST metrics, Tempo and Jaeger.

Only bounded aggregates leave this module. Trace IDs, span attributes and raw series are never returned.
"""
import base64
import ipaddress
import json
import math
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

KINDS = ('prometheus', 'rest_metrics', 'tempo', 'jaeger')
AUTH_KINDS = ('none', 'bearer_env', 'basic_env', 'header_env', 'azure_managed', 'aws_sigv4', 'gcp_managed')
METRICS = ('cpu_percent', 'memory_percent', 'requests_per_second', 'error_rate_pct', 'latency_p95_ms', 'custom')
SCHEDULES = ('hourly', 'daily', 'manual')
SECRET_REF = r'CLOUDSAVER_OBSERVABILITY_SECRET_[A-Z0-9_]{1,80}'
HEADER = r'[A-Za-z][A-Za-z0-9-]{0,63}'
ID = r'[a-z0-9_-]{1,40}'
LABEL = r'[A-Za-z_][A-Za-z0-9_.]{0,79}'
FIELD_PATH = r'[A-Za-z0-9_]{1,60}(\.[A-Za-z0-9_]{1,60}){0,7}'
SERVICE = r'[A-Za-z0-9_.:/-]{1,120}'
PLACEHOLDERS = ('{start_iso}', '{end_iso}', '{start_epoch}', '{end_epoch}', '{step_seconds}')
MAX_QUERIES, MAX_QUERY_LENGTH, MAX_SERIES, MAX_SERVICES, MAX_BYTES = 20, 2000, 2000, 50, 4_000_000
FORBIDDEN_HEADERS = {'host', 'content-length', 'cookie', 'transfer-encoding', 'connection'}


class SourceError(Exception):
    """A fixed, non-sensitive error code. Provider response text never travels with it."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _match(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def allowed_hosts():
    return {h.strip().lower() for h in os.getenv('CLOUDSAVER_OBSERVABILITY_ALLOWED_HOSTS', '').split(',') if h.strip()}


def check_url(url, *, resolve=True):
    """HTTPS only, no credentials or query, and no private, loopback, link-local or metadata address unless allowlisted."""
    if not isinstance(url, str) or len(url) > 500:
        raise ValueError('Use an HTTPS URL of 500 characters or fewer.')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Use an HTTPS URL without credentials, a query string or a fragment.')
    host = parts.hostname.lower()
    if host in allowed_hosts() or not resolve:
        return host
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise ValueError('The connector host could not be resolved.') from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split('%')[0])
        if not address.is_global or address.is_multicast:
            raise ValueError('The connector host resolves to a private or reserved address. Ask your operator to allow it.')
    return host


def validate(raw, tenant):
    """Normalize a connector definition; raises ValueError with a user-facing message."""
    if not isinstance(raw, dict):
        raise ValueError('Connector details are required.')
    allowed = {'name', 'kind', 'base_url', 'auth_kind', 'secret_ref', 'header_name', 'aws_account_id', 'gcp_project_id',
               'queries', 'services', 'mappings', 'thresholds', 'schedule', 'trace_window_hours'}
    if set(raw) - allowed:
        raise ValueError('Remove unsupported connector fields: ' + ', '.join(sorted(set(raw) - allowed)) + '.')
    name = str(raw.get('name', '')).strip()
    if not 1 <= len(name) <= 80:
        raise ValueError('Enter a connector name of 1–80 characters.')
    kind = raw.get('kind')
    if kind not in KINDS:
        raise ValueError('Choose Prometheus, REST metrics, Tempo or Jaeger.')
    base = str(raw.get('base_url', '')).strip()
    base = base if base.endswith('/') else base + '/'
    host = check_url(base, resolve=False)
    auth = raw.get('auth_kind', 'none')
    if auth not in AUTH_KINDS:
        raise ValueError('Choose a supported authentication method.')
    item = dict(name=name, kind=kind, base_url=base, auth_kind=auth, secret_ref=None, header_name=None, aws_account_id=None,
                gcp_project_id=None, queries=[], services=[], mappings={}, thresholds={}, schedule=raw.get('schedule', 'hourly'),
                trace_window_hours=raw.get('trace_window_hours', 1))
    if item['schedule'] not in SCHEDULES:
        raise ValueError('Choose an hourly, daily or manual schedule.')
    if type(item['trace_window_hours']) is not int or not 1 <= item['trace_window_hours'] <= 24:
        raise ValueError('Trace window must be 1–24 hours.')
    if auth in ('bearer_env', 'basic_env', 'header_env'):
        if not _match(SECRET_REF, raw.get('secret_ref')):
            raise ValueError('Secret reference must name an environment variable that starts with CLOUDSAVER_OBSERVABILITY_SECRET_.')
        item['secret_ref'] = raw['secret_ref']
    if auth == 'header_env':
        if not _match(HEADER, raw.get('header_name')) or raw['header_name'].lower() in FORBIDDEN_HEADERS:
            raise ValueError('Enter a valid header name for the secret.')
        item['header_name'] = raw['header_name']
    if auth == 'azure_managed' and not host.endswith('.prometheus.monitor.azure.com'):
        raise ValueError('Azure managed identity is supported only for Azure Monitor managed Prometheus endpoints.')
    if auth == 'aws_sigv4':
        account = raw.get('aws_account_id')
        if not any(a.get('account_id') == account for a in tenant.get('aws_accounts', [])):
            raise ValueError('Choose an AWS account that belongs to this workspace.')
        if not re.fullmatch(r'aps-workspaces\.[a-z]{2}(-[a-z]+)+-\d\.amazonaws\.com', host):
            raise ValueError('AWS SigV4 is supported only for Amazon Managed Service for Prometheus endpoints.')
        item['aws_account_id'] = account
    if auth == 'gcp_managed':
        project = raw.get('gcp_project_id')
        if not any(p.get('project_id') == project for p in tenant.get('gcp_projects', [])):
            raise ValueError('Choose a Google Cloud project that belongs to this workspace.')
        if host != 'monitoring.googleapis.com':
            raise ValueError('Google managed identity is supported only for Google Cloud Managed Service for Prometheus.')
        item['gcp_project_id'] = project
    mappings = raw.get('mappings') or {}
    if not isinstance(mappings, dict) or set(mappings) - {'resource_label', 'service_resources'}:
        raise ValueError('Mappings support resource_label and service_resources.')
    if mappings.get('resource_label') is not None:
        if not _match(LABEL, mappings['resource_label']):
            raise ValueError('Resource label must be a label or field name, such as azure_resource_id or instance.')
        item['mappings']['resource_label'] = mappings['resource_label']
    services_map = mappings.get('service_resources') or {}
    if not isinstance(services_map, dict) or len(services_map) > MAX_SERVICES or any(
            not _match(SERVICE, k) or not isinstance(v, str) or not 1 <= len(v) <= 2048 for k, v in services_map.items()):
        raise ValueError('Service mappings must link up to 50 service names to resource IDs.')
    if services_map:
        item['mappings']['service_resources'] = dict(services_map)
    thresholds = raw.get('thresholds') or {}
    if not isinstance(thresholds, dict) or set(thresholds) - {'latency_p95_ms', 'error_rate_pct'}:
        raise ValueError('Thresholds support latency_p95_ms and error_rate_pct.')
    for key, default, limit in (('latency_p95_ms', 500, 600000), ('error_rate_pct', 1, 100)):
        value = thresholds.get(key, default)
        if type(value) not in (int, float) or not 0 < value <= limit:
            raise ValueError(f'{key} must be greater than 0 and at most {limit}.')
        item['thresholds'][key] = value
    if kind in ('prometheus', 'rest_metrics'):
        queries = raw.get('queries') or []
        if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES:
            raise ValueError('Add 1–20 queries.')
        if not item['mappings'].get('resource_label'):
            raise ValueError('Add a resource label so CloudSaver can link series to resources.')
        seen = set()
        for query in queries:
            item['queries'].append(_query(kind, query, seen))
    else:
        services = raw.get('services') or list(item['mappings'].get('service_resources', {}))
        if not isinstance(services, list) or not 1 <= len(services) <= MAX_SERVICES or any(not _match(SERVICE, s) for s in services):
            raise ValueError('Add 1–50 service names to read traces for.')
        item['services'] = sorted(set(services))
    return item


def _query(kind, query, seen):
    if not isinstance(query, dict):
        raise ValueError('Each query needs an ID, metric and query.')
    qid, metric = query.get('id'), query.get('metric', 'custom')
    if not _match(ID, qid) or qid in seen:
        raise ValueError('Each query needs a unique lowercase ID.')
    seen.add(qid)
    if metric not in METRICS:
        raise ValueError('Choose a supported metric type for query ' + qid + '.')
    unit = str(query.get('unit', ''))[:20]
    if kind == 'prometheus':
        if set(query) - {'id', 'metric', 'unit', 'promql'}:
            raise ValueError('Prometheus queries support id, metric, unit and promql.')
        promql = query.get('promql')
        if not isinstance(promql, str) or not 1 <= len(promql.strip()) <= MAX_QUERY_LENGTH:
            raise ValueError('PromQL for query ' + qid + ' must be 1–2,000 characters.')
        return dict(id=qid, metric=metric, unit=unit, promql=promql.strip())
    if set(query) - {'id', 'metric', 'unit', 'path', 'params', 'series_path', 'resource_field', 'points_path', 'timestamp_field', 'value_field'}:
        raise ValueError('Remove unsupported fields from REST query ' + qid + '.')
    path = query.get('path', '')
    if not isinstance(path, str) or len(path) > 300 or path.startswith('/') or '..' in path or '://' in path or '?' in path or '#' in path \
            or not re.fullmatch(r'[A-Za-z0-9_./~-]*', path):
        raise ValueError('REST path for query ' + qid + ' must be relative to the base URL, without a query string.')
    params = query.get('params') or {}
    if not isinstance(params, dict) or len(params) > 20 or any(
            not _match(r'[A-Za-z0-9_.\[\]-]{1,60}', k) or not isinstance(v, str) or len(v) > 200 for k, v in params.items()):
        raise ValueError('REST parameters for query ' + qid + ' must be up to 20 short text values.')
    fields = {}
    for key in ('series_path', 'resource_field', 'points_path', 'timestamp_field', 'value_field'):
        value = query.get(key)
        if value is not None and not _match(FIELD_PATH, value):
            raise ValueError(f'{key} for query {qid} must be a dotted field path.')
        fields[key] = value
    if not fields['resource_field'] or not fields['points_path']:
        raise ValueError('REST query ' + qid + ' needs resource_field and points_path.')
    return dict(id=qid, metric=metric, unit=unit, path=path, params=dict(params), **fields)


class Client:
    """GET-only client bound to one connector base URL."""

    def __init__(self, connector, tenant, *, transport=None):
        self.connector, self.tenant, self.base = connector, tenant, connector['base_url']
        self.host = urlsplit(self.base).hostname.lower()
        self.headers, self.signer = self._auth()
        self.http = httpx.Client(timeout=httpx.Timeout(25, connect=5), follow_redirects=False, transport=transport)

    def _secret(self):
        value = os.getenv(self.connector.get('secret_ref') or '')
        if not value:
            raise SourceError('OBSERVABILITY_SECRET_UNAVAILABLE')
        return value

    def _auth(self):
        kind = self.connector['auth_kind']
        if kind == 'none':
            return {}, None
        if kind == 'bearer_env':
            return {'Authorization': 'Bearer ' + self._secret()}, None
        if kind == 'basic_env':
            return {'Authorization': 'Basic ' + base64.b64encode(self._secret().encode()).decode()}, None
        if kind == 'header_env':
            return {self.connector['header_name']: self._secret()}, None
        try:
            if kind == 'azure_managed':
                from app.cloud_identity import azure_credential
                credential = azure_credential(self.tenant)
                try:
                    return {'Authorization': 'Bearer ' + credential.get_token('https://prometheus.monitor.azure.com/.default').token}, None
                finally:
                    credential.close()
            if kind == 'gcp_managed':
                from app.cloud_identity import gcp_credentials
                from google.auth.transport.requests import Request
                source = next(p for p in self.tenant.get('gcp_projects', []) if p['project_id'] == self.connector['gcp_project_id'])
                credential = gcp_credentials(source, tenant=self.tenant, scopes=['https://www.googleapis.com/auth/monitoring.read'])
                credential.refresh(Request())
                return {'Authorization': 'Bearer ' + credential.token}, None
            if kind == 'aws_sigv4':
                from app.cloud_identity import aws_session
                from botocore.auth import SigV4Auth
                from botocore.awsrequest import AWSRequest
                source = next(a for a in self.tenant.get('aws_accounts', []) if a['account_id'] == self.connector['aws_account_id'])
                session, region = aws_session(source, tenant=self.tenant), self.host.split('.')[1]
                def sign(url):
                    request = AWSRequest(method='GET', url=url)
                    SigV4Auth(session.get_credentials().get_frozen_credentials(), 'aps', region).add_auth(request)
                    return dict(request.headers)
                return {}, sign
        except SourceError:
            raise
        except Exception:
            raise SourceError('OBSERVABILITY_IDENTITY_UNAVAILABLE') from None
        raise SourceError('OBSERVABILITY_AUTH_UNSUPPORTED')

    def get(self, path, params=None):
        url = str(httpx.URL(self.base + path, params={k: str(v) for k, v in (params or {}).items()}))
        if not url.startswith(self.base) or urlsplit(url).hostname.lower() != self.host:
            raise SourceError('OBSERVABILITY_DESTINATION_CHANGED')
        try:
            check_url(self.base)
        except ValueError:
            raise SourceError('OBSERVABILITY_DESTINATION_BLOCKED') from None
        headers = dict(self.headers, Accept='application/json')
        if self.signer:
            headers.update(self.signer(url))
        from app.provider_retry import read_json, ProviderReadError, ProviderDeferred
        try:
            return read_json(self.http,'GET',url,headers=headers,max_bytes=MAX_BYTES,
                quota_key='observability:'+self.tenant['tenant_id']+':'+self.host)
        except ProviderDeferred:
            raise SourceError('OBSERVABILITY_PROVIDER_THROTTLED') from None
        except ProviderReadError as error:
            raise SourceError('OBSERVABILITY_AUTH_REJECTED' if error.status_code in (401,403) else 'OBSERVABILITY_QUERY_REJECTED') from None
        except SourceError:
            raise
        except (httpx.HTTPError, ValueError):
            raise SourceError('OBSERVABILITY_SOURCE_UNAVAILABLE') from None

    def close(self):
        self.http.close()


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value):
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r'\d+(\.\d+)?', value)):
        number = float(value)
        return number / 1000 if number > 1e12 else number
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            return None
    return None


def summarize(points, window_seconds, step_seconds):
    values = sorted(v for _, v in points if v is not None)
    if not values:
        return None
    rank = lambda q: values[min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))]
    expected = max(1, int(window_seconds // step_seconds))
    return dict(samples=len(values), coverage_pct=round(min(100.0, 100 * len(values) / expected), 1),
                p50=round(rank(.5), 4), p95=round(rank(.95), 4), max=round(values[-1], 4), avg=round(sum(values) / len(values), 4))


def window(connector, now=None):
    end = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    if connector['kind'] in ('tempo', 'jaeger'):
        return end - timedelta(hours=connector['trace_window_hours']), end, 60
    if connector['schedule'] == 'daily':
        return end - timedelta(days=30), end, 3600
    return end - timedelta(days=7), end, 300


def _path(value, path):
    for part in (path.split('.') if path else []):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _series(query, resource, points, seconds, step):
    return dict(query_id=query['id'], metric=query['metric'], unit=query['unit'],
                resource_id=resource if isinstance(resource, str) and 0 < len(resource) <= 2048 else None,
                summary=summarize(points, seconds, step))


def prometheus(client, connector, start, end, step, *, limit_queries=None):
    label, rows = connector['mappings']['resource_label'], []
    for query in connector['queries'][:limit_queries]:
        body = client.get('api/v1/query_range', dict(query=query['promql'], start=int(start.timestamp()), end=int(end.timestamp()), step=step))
        data = body.get('data') if isinstance(body, dict) else None
        if body.get('status') != 'success' or not isinstance(data, dict) or data.get('resultType') != 'matrix':
            raise SourceError('OBSERVABILITY_QUERY_REJECTED')
        for item in data.get('result') or []:
            points = [(_timestamp(t), _number(v)) for t, v in (item.get('values') or [])]
            rows.append(_series(query, (item.get('metric') or {}).get(label), points, (end - start).total_seconds(), step))
            if len(rows) > MAX_SERIES:
                raise SourceError('OBSERVABILITY_SERIES_LIMIT')
    return dict(series=rows, services=[], warnings=[])


def rest_metrics(client, connector, start, end, step, *, limit_queries=None):
    values = {'{start_iso}': start.isoformat(), '{end_iso}': end.isoformat(), '{start_epoch}': str(int(start.timestamp())),
              '{end_epoch}': str(int(end.timestamp())), '{step_seconds}': str(step)}
    rows = []
    for query in connector['queries'][:limit_queries]:
        params = {}
        for key, template in query['params'].items():
            for placeholder, replacement in values.items():
                template = template.replace(placeholder, replacement)
            params[key] = template
        body = client.get(query['path'], params)
        series = _path(body, query.get('series_path')) if query.get('series_path') else body
        if not isinstance(series, list):
            raise SourceError('OBSERVABILITY_RESPONSE_UNMAPPED')
        for item in series:
            raw = _path(item, query['points_path'])
            if not isinstance(raw, list):
                continue
            points = []
            for point in raw:
                if isinstance(point, list) and len(point) >= 2:
                    points.append((_timestamp(point[0]), _number(point[1])))
                elif isinstance(point, dict):
                    points.append((_timestamp(_path(point, query.get('timestamp_field') or 'timestamp')), _number(_path(point, query.get('value_field') or 'value'))))
            rows.append(_series(query, _path(item, query['resource_field']), points, (end - start).total_seconds(), step))
            if len(rows) > MAX_SERIES:
                raise SourceError('OBSERVABILITY_SERIES_LIMIT')
    return dict(series=rows, services=[], warnings=[])


def _tempo_values(body, combine):
    series = body.get('series') if isinstance(body, dict) else None
    if not isinstance(series, list):
        raise SourceError('OBSERVABILITY_QUERY_REJECTED')
    merged = {}
    for item in series:
        for sample in item.get('samples') or []:
            at, value = _timestamp(sample.get('timestampMs')), _number(sample.get('value'))
            if at is None or value is None:
                continue
            merged[at] = combine(merged[at], value) if at in merged else value
    return sorted(merged.items())


def tempo(client, connector, start, end, step, *, limit_services=None):
    rows, seconds = [], (end - start).total_seconds()
    for service in connector['services'][:limit_services]:
        selector = '{resource.service.name="' + service + '"}'
        errors = '{resource.service.name="' + service + '" && status=error}'
        read = lambda q: client.get('api/metrics/query_range', dict(q=q, start=int(start.timestamp()), end=int(end.timestamp()), step=f'{step}s'))
        rate = _tempo_values(read(selector + ' | rate()'), lambda a, b: a + b)
        failed = _tempo_values(read(errors + ' | rate()'), lambda a, b: a + b)
        p95 = _tempo_values(read(selector + ' | quantile_over_time(duration, .95)'), max)
        p50 = _tempo_values(read(selector + ' | quantile_over_time(duration, .5)'), max)
        rps = sum(v for _, v in rate) / len(rate) if rate else None
        error_rps = sum(v for _, v in failed) / len(failed) if failed else 0.0
        rows.append(dict(service=service, requests_per_second=round(rps, 4) if rps is not None else None,
                         error_rate_pct=round(100 * error_rps / rps, 3) if rps else None,
                         latency_p50_ms=round(1000 * (summarize(p50, seconds, step) or {}).get('p50', 0), 2) if p50 else None,
                         latency_p95_ms=round(1000 * (summarize(p95, seconds, step) or {}).get('p95', 0), 2) if p95 else None,
                         coverage_pct=(summarize(rate, seconds, step) or {}).get('coverage_pct', 0.0), sampled=False, dependencies=[]))
    return dict(series=[], services=rows, warnings=['Tempo service dependencies are not read. Use Prometheus service graph metrics for dependencies.'])


def jaeger(client, connector, start, end, step, *, limit_services=None):
    rows, begin_us, end_us = [], int(start.timestamp() * 1e6), int(end.timestamp() * 1e6)
    for service in connector['services'][:limit_services]:
        body = client.get('api/traces', dict(service=service, start=begin_us, end=end_us, limit=500))
        traces = body.get('data') if isinstance(body, dict) else None
        if not isinstance(traces, list):
            raise SourceError('OBSERVABILITY_QUERY_REJECTED')
        durations, failures = [], 0
        for trace in traces:
            processes = trace.get('processes') or {}
            spans = [s for s in trace.get('spans') or [] if (processes.get(s.get('processID')) or {}).get('serviceName') == service]
            if not spans:
                continue
            ids = {s.get('spanID') for s in spans}
            entry = next((s for s in spans if not any(r.get('spanID') in ids for r in s.get('references') or [])), spans[0])
            duration = _number(entry.get('duration'))
            if duration is not None:
                durations.append((0, duration / 1000))
            failures += any(t.get('key') == 'error' and t.get('value') in (True, 'true') or t.get('key') == 'otel.status_code' and t.get('value') == 'ERROR'
                            for s in spans for t in s.get('tags') or [])
        summary = summarize(durations, 1, 1)
        rows.append(dict(service=service, requests_per_second=None, traces_sampled=len(durations),
                         error_rate_pct=round(100 * failures / len(durations), 3) if durations else None,
                         latency_p50_ms=summary['p50'] if summary else None, latency_p95_ms=summary['p95'] if summary else None,
                         coverage_pct=None, sampled=True, dependencies=[]))
    if limit_services is None:
        lookback = int((end - start).total_seconds() * 1000)
        body = client.get('api/dependencies', dict(endTs=int(end.timestamp() * 1000), lookback=lookback))
        links = body.get('data') if isinstance(body, dict) else None
        for row in rows:
            row['dependencies'] = sorted(({'service': d.get('child'), 'calls': d.get('callCount')} for d in links or []
                                          if isinstance(d, dict) and d.get('parent') == row['service'] and _match(SERVICE, d.get('child'))),
                                         key=lambda d: -(_number(d['calls']) or 0))[:20]
    return dict(series=[], services=rows, warnings=['Jaeger latency and error rate come from up to 500 sampled traces per service. Request volume is not inferred from samples.'])


READERS = {'prometheus': prometheus, 'rest_metrics': rest_metrics, 'tempo': tempo, 'jaeger': jaeger}


def collect(connector, tenant, *, now=None, transport=None, probe=False):
    start, end, step = window(connector, now)
    if probe:
        start = end - timedelta(hours=1)
    client = Client(connector, tenant, transport=transport)
    try:
        reader = READERS[connector['kind']]
        limit = dict(limit_queries=1) if connector['kind'] in ('prometheus', 'rest_metrics') else dict(limit_services=1)
        result = reader(client, connector, start, end, step, **(limit if probe else {}))
    finally:
        client.close()
    labeled = sum(1 for s in result['series'] if s['resource_id'])
    result.update(window_start=start.isoformat(), window_end=end.isoformat(), step_seconds=step,
                  mapping_coverage=dict(series=len(result['series']), labeled=labeled, services=len(result['services']),
                                        mapped_services=sum(1 for s in result['services'] if s['service'] in connector['mappings'].get('service_resources', {}))))
    return result


MESSAGES = {
    'OBSERVABILITY_SECRET_UNAVAILABLE': "The secret reference isn't set on the CloudSaver services. Ask your operator to add it.",
    'OBSERVABILITY_IDENTITY_UNAVAILABLE': "The workspace cloud identity couldn't get a token for this endpoint.",
    'OBSERVABILITY_AUTH_REJECTED': 'The endpoint rejected the credentials. Check the secret or identity permissions.',
    'OBSERVABILITY_QUERY_REJECTED': "The endpoint rejected a query or returned an unexpected format. Check the queries and URL.",
    'OBSERVABILITY_SOURCE_UNAVAILABLE': "The endpoint couldn't be reached or returned invalid JSON.",
    'OBSERVABILITY_RESPONSE_TOO_LARGE': 'The response is larger than 4 MB. Narrow the query.',
    'OBSERVABILITY_SERIES_LIMIT': 'The queries returned more than 2,000 series. Aggregate them further.',
    'OBSERVABILITY_RESPONSE_UNMAPPED': "The response doesn't match series_path. Check the field mapping.",
    'OBSERVABILITY_DESTINATION_BLOCKED': 'The endpoint resolves to a private or reserved address. Ask your operator to allow it.',
    'OBSERVABILITY_DESTINATION_CHANGED': 'The request destination changed. Check the base URL and path.',
}


def message(code):
    return MESSAGES.get(code, 'Something went wrong. If the issue persists, contact Support.')
