"""Read-only GCP inventory, with complete Monitoring evidence for SQL idleness."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from app.cloud_http import JSONReader, pages
from app.cloud_scope import NAME, matches, validate_finding_scope
from app.scanner import ScanError
from app.inventory import FindingBatch, observation

COMPUTE = 'https://compute.googleapis.com/compute/v1/projects/'
SQL = 'https://sqladmin.googleapis.com/sql/v1beta4/projects/'
MONITORING = 'https://monitoring.googleapis.com/v3/projects/'
SQL_METRIC = 'cloudsql.googleapis.com/database/network/connections'


def finding(project, row, kind, *, regional=False):
    name = row.get('name')
    if not matches(NAME, name):
        raise ScanError('GCP returned an invalid resource name')
    if kind == 'instances':
        rid = f'//sqladmin.googleapis.com/projects/{project}/instances/{name}'
        region, rule, resource_type = row.get('region'), 'GCP_IDLE_CLOUD_SQL', 'sqladmin.googleapis.com/Instance'
        details = 'Development/staging Cloud SQL instance has a complete 14-day hourly connection window with zero connections. Validate replicas, jobs and recovery requirements.'
    else:
        location_url = row.get('region') if regional else row.get('zone')
        location = urlsplit(location_url or '').path.rsplit('/', 1)[-1]
        category = 'regions' if regional else 'zones'
        rid = f'//compute.googleapis.com/projects/{project}/{category}/{location}/{kind}/{name}'
        region = location if regional else location.rsplit('-', 1)[0]
        if kind == 'disks':
            rule, resource_type = 'GCP_UNATTACHED_DISK', 'compute.googleapis.com/Disk'
            details = 'Ready persistent disk reports no users. No idle duration, backup assurance or verified savings is implied.'
        else:
            rule, resource_type = 'GCP_UNASSIGNED_ADDRESS', 'compute.googleapis.com/Address'
            details = 'Reserved external IPv4 address reports no users. Validate reservations and forwarding dependencies before changes.'
    return dict(rule_id=rule, severity='HIGH' if kind == 'instances' else 'MEDIUM', cloud_provider='gcp',
                scope_id=project, subscription_id=project, region=region, resource_id=rid,
                resource_name=name, resource_group=project, resource_type=resource_type,
                estimated_monthly_waste_usd=None, details=details,
                evidence={'source': 'Google Cloud APIs', 'state': row.get('status', row.get('state')),
                          'labels': row.get('labels') or (row.get('settings') or {}).get('userLabels') or {}})


def _verify_self_link(row, project, rid):
    link = row.get('selfLink')
    if not isinstance(link, str):
        raise ScanError('GCP returned no canonical resource identity')
    parsed = urlsplit(link)
    # Compute selfLink may use www.googleapis.com or compute.googleapis.com.
    if (parsed.scheme != 'https' or parsed.hostname not in ('www.googleapis.com', 'compute.googleapis.com')
            or parsed.query or parsed.fragment or parsed.username or parsed.password
            or not parsed.path.endswith(rid.split('googleapis.com', 1)[1])):
        raise ScanError('GCP returned an out-of-scope resource identity')


def sql_idle_evidence(reader, project, instance, now):
    """Require 336 consecutive UTC hourly maxima, including every returned series.

    No telemetry means unknown. This deliberately does not interpret gaps as zero.
    """
    end = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=14)
    expected = {int((start + timedelta(hours=i)).timestamp()) for i in range(1, 337)}
    params = {'filter': f'metric.type = "{SQL_METRIC}" AND resource.type = "cloudsql_database" AND resource.labels.database_id = "{project}:{instance}"',
              'interval.startTime': start.isoformat(), 'interval.endTime': end.isoformat(),
              'aggregation.alignmentPeriod': '3600s', 'aggregation.perSeriesAligner': 'ALIGN_MAX',
              'view': 'FULL', 'pageSize': 1000}
    series = []
    for page in pages(reader, MONITORING + project + '/timeSeries', params):
        batch = page.get('timeSeries', [])
        if not isinstance(batch, list) or page.get('executionErrors'):
            raise ScanError('Monitoring returned incomplete SQL telemetry')
        series.extend(batch)
        if len(series) > 1000:
            raise ScanError('Monitoring SQL series limit exceeded')
    if not series:
        return None
    for item in series:
        resource, metric = item.get('resource', {}), item.get('metric', {})
        if (resource.get('type') != 'cloudsql_database' or resource.get('labels', {}).get('database_id') != f'{project}:{instance}'
                or resource.get('labels', {}).get('project_id') != project or metric.get('type') != SQL_METRIC):
            raise ScanError('Monitoring returned SQL telemetry outside the authorized scope')
        observed = set()
        for point in item.get('points', []):
            try:
                time = datetime.fromisoformat(point['interval']['endTime'].replace('Z', '+00:00'))
                stamp = int(time.timestamp())
                value = point['value']
                raw = value['int64Value'] if 'int64Value' in value else value['doubleValue']
                if time.tzinfo is None or stamp not in expected or stamp in observed or float(raw) != 0:
                    return None
                observed.add(stamp)
            except (KeyError, TypeError, ValueError, OverflowError):
                return None
        if observed != expected:
            return None
    return dict(window_start=start.isoformat(), window_end=end.isoformat(), aligned_hours=336,
                series_count=len(series), maximum_connections=0, metric=SQL_METRIC)


def scan_gcp_project(source, *, reader=None, now=None):
    project, regions = source['project_id'], source['regions']
    own_reader = reader is None
    if own_reader:
        from app.cloud_identity import CredentialError, gcp_credentials
        try:
            reader = JSONReader(credentials=gcp_credentials(source))
        except CredentialError:
            raise ScanError('The GCP workload identity credential is unavailable') from None
        except Exception:
            raise ScanError('The GCP API client could not be initialized') from None
    findings, inventory, seen = [], [], set()
    tenant = {'gcp_projects': [source]}

    def consume(row, kind, regional):
        # Region API returns only regional objects; aggregated disks are zonal.
        result = finding(project, row, kind, regional=regional)
        _verify_self_link(row, project, result['resource_id'])
        validate_finding_scope(result, tenant)
        if result['resource_id'] in seen:
            return
        seen.add(result['resource_id'])
        inventory.append(observation(result))
        if len(seen) > 100000:
            raise ScanError('GCP inventory resource limit exceeded')
        users = row.get('users')
        if users is not None and not isinstance(users, list):
            raise ScanError('GCP returned malformed resource associations')
        if ((kind == 'disks' and row.get('status') == 'READY' and not users)
                or (kind == 'addresses' and row.get('status') == 'RESERVED' and not users
                    and row.get('addressType') == 'EXTERNAL' and row.get('ipVersion') == 'IPV4')):
            findings.append(result)

    try:
        for kind in ('disks', 'addresses'):
            for page in pages(reader, COMPUTE + project + '/aggregated/' + kind, {'maxResults': 500, 'returnPartialSuccess': 'false'}):
                groups = page.get('items', {})
                if not isinstance(groups, dict):
                    raise ScanError('GCP returned malformed aggregated inventory')
                for scope, group in groups.items():
                    if group.get('warning', {}).get('code') not in (None, 'NO_RESULTS_ON_PAGE'):
                        raise ScanError('GCP returned an incomplete inventory scope')
                    if not scope.startswith(('zones/', 'regions/', 'global')):
                        raise ScanError('GCP returned an invalid inventory scope')
                    for row in group.get(kind, []):
                        # Only regional external addresses are supported; global addresses remain excluded.
                        if kind == 'addresses' and not scope.startswith('regions/'):
                            continue
                        if scope.startswith('regions/') and scope.split('/', 1)[1] not in regions:
                            continue
                        consume(row, kind, scope.startswith('regions/'))
            if kind == 'disks':
                for region in regions:
                    for page in pages(reader, COMPUTE + project + '/regions/' + region + '/disks', {'maxResults': 500}):
                        for row in page.get('items', []):
                            consume(row, kind, True)
        for page in pages(reader, SQL + project + '/instances', {'maxResults': 500}):
            for row in page.get('items', []):
                if row.get('project') != project or not matches(NAME, row.get('name')):
                    raise ScanError('Cloud SQL returned an out-of-scope instance')
                if row.get('region') not in regions:
                    continue
                result = finding(project, row, 'instances')
                validate_finding_scope(result, tenant)
                inventory.append(observation(result))
                environment = row.get('settings', {}).get('userLabels', {}).get('environment')
                if row.get('state') != 'RUNNABLE' or environment not in ('dev', 'development', 'staging'):
                    continue
                evidence = sql_idle_evidence(reader, project, row['name'], now or datetime.now(timezone.utc))
                if evidence:
                    result = finding(project, row, 'instances')
                    validate_finding_scope(result, tenant)
                    result['evidence'].update(evidence)
                    findings.append(result)
        return FindingBatch(findings, inventory)
    except ScanError:
        raise
    except Exception:
        raise ScanError('GCP scan failed; no partial inventory was saved') from None
    finally:
        if own_reader:
            reader.close()
