"""Derive assessment evidence fields from saved configuration, metrics, and relationships."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.telemetry_contract import moment


def _metric_summary(evidence: dict, key: str) -> dict | None:
    metrics = evidence.get('metrics') or {}
    summaries = evidence.get('metric_summaries') or {}
    if isinstance(summaries.get(key), dict):
        return summaries[key]
    series = metrics.get(key)
    return series if isinstance(series, dict) else None


def _summary_stat(evidence: dict, metric_key: str, stat: str = 'p99') -> float | None:
    row = (evidence.get('metric_summaries') or {}).get(metric_key)
    if isinstance(row, dict) and type(row.get(stat)) in (int, float):
        return float(row[stat])
    return None


def _series_minimum(evidence: dict, key: str) -> float | None:
    series = (evidence.get('metrics') or {}).get(key)
    if not isinstance(series, dict):
        return None
    points = series.get('points') or []
    values = [p.get('value') for p in points if isinstance(p, dict) and type(p.get('value')) in (int, float)]
    if not values:
        summary = _metric_summary(evidence, key)
        if summary and type(summary.get('minimum')) in (int, float):
            return float(summary['minimum'])
        if summary and type(summary.get('p99')) in (int, float):
            return float(summary['p99'])
        return None
    return float(min(values))


def _series_p99(evidence: dict, key: str) -> float | None:
    summary = _metric_summary(evidence, key)
    if summary and type(summary.get('p99')) in (int, float):
        return float(summary['p99'])
    return None


def _set_bool(evidence: dict, key: str, value: bool | None) -> None:
    if value is None or key in evidence and isinstance(evidence[key], bool):
        return
    evidence[key] = value


def _set_number(evidence: dict, key: str, value: float | None) -> None:
    if value is None or not math.isfinite(value) or value < 0:
        return
    if key not in evidence:
        evidence[key] = int(value) if value == int(value) else round(value, 4)


def _state_duration_days(evidence: dict, *, now: datetime | None = None) -> float | None:
    """Days in the current complete state_history interval, else age since created_at."""
    current = now or datetime.now(timezone.utc)
    history = evidence.get('state_history')
    if isinstance(history, list) and history:
        item = history[-1]
        if isinstance(item, dict) and item.get('complete') is True:
            start, end = moment(item.get('start')), moment(item.get('end')) or current
            if start and end and end > start:
                return (end - start).total_seconds() / 86400.0
    created = moment(evidence.get('created_at'))
    if created and created <= current:
        return (current - created).total_seconds() / 86400.0
    return None


def apply_derived_facts(resource: dict) -> dict:
    """Populate numeric and boolean evidence used by pillar checks when data exists."""
    evidence = resource.setdefault('evidence', {})
    props = evidence.get('typed_configuration')
    if not isinstance(props, dict):
        props = {}

    rtype = (resource.get('resource_type') or '').lower()

    if rtype == 'microsoft.compute/virtualmachines':
        network = props.get('networkProfile') or {}
        nics = network.get('networkInterfaces') or []
        has_nic = isinstance(nics, list) and any(isinstance(n, dict) and n.get('id') for n in nics)
        edges = resource.get('dependency_refs') or []
        public_nic = any(
            isinstance(e, dict) and e.get('relationship') == 'nic_to_ip' for e in edges
        )
        if public_nic:
            _set_bool(evidence, 'public_admin_ingress', True)
        elif has_nic and edges:
            _set_bool(evidence, 'public_admin_ingress', False)
        os_profile = props.get('osProfile') or {}
        if isinstance(os_profile.get('linuxConfiguration'), dict) or isinstance(os_profile.get('windowsConfiguration'), dict):
            _set_bool(evidence, 'monitoring_enabled', True)
        diagnostics = props.get('diagnosticsProfile') or {}
        if isinstance(diagnostics.get('bootDiagnostics'), dict) and diagnostics['bootDiagnostics'].get('enabled') is True:
            _set_bool(evidence, 'monitoring_enabled', True)
        power = (evidence.get('power_state') or '').lower()
        if 'deallocated' in power or 'stopped' in power:
            _set_number(evidence, 'stopped_days', _state_duration_days(evidence))

    if rtype == 'microsoft.compute/disks':
        if evidence.get('disk_state') == 'Unattached':
            _set_number(evidence, 'unattached_days', _state_duration_days(evidence))

    if rtype == 'microsoft.storage/storageaccounts':
        if evidence.get('supports_https_traffic_only') is True:
            _set_bool(evidence, 'https_only', True)
        if evidence.get('tls_required') is True:
            _set_bool(evidence, 'tls_required', True)
        if type(evidence.get('allow_blob_public_access')) is bool:
            _set_bool(evidence, 'public_snapshot', evidence['allow_blob_public_access'])

    if rtype == 'microsoft.network/publicipaddresses':
        if evidence.get('association_verified') is False:
            _set_bool(evidence, 'unrestricted_ingress', False)

    if rtype in ('microsoft.web/sites', 'microsoft.web/serverfarms'):
        site_config = props.get('siteConfig') if rtype == 'microsoft.web/sites' else {}
        if isinstance(site_config, dict):
            if site_config.get('healthCheckPath'):
                _set_bool(evidence, 'health_probes_enabled', True)
            elif site_config.get('alwaysOn') is False and type(evidence.get('hosted_app_count')) is int:
                _set_bool(evidence, 'health_probes_enabled', False)
            if props.get('httpsOnly') is True or site_config.get('minTlsVersion'):
                _set_bool(evidence, 'https_only', True)
        if props.get('keyVaultReferenceIdentity') or (site_config or {}).get('appSettings'):
            settings = (site_config or {}).get('appSettings') or []
            if any(isinstance(s, dict) and '@Microsoft.KeyVault' in str(s.get('value', '')) for s in settings):
                _set_bool(evidence, 'managed_secrets', True)

    if type(evidence.get('commitment_locked')) is bool:
        evidence['commitment_lock_conflict'] = evidence['commitment_locked']

    refs = resource.get('dependency_refs') or []
    if isinstance(refs, list) and refs:
        verified = []
        rid = resource.get('resource_id')
        for edge in refs:
            if not isinstance(edge, dict) or edge.get('verification_state') != 'verified':
                continue
            if edge.get('from_resource_id') == rid:
                other = edge.get('to_resource_id')
            elif edge.get('to_resource_id') == rid:
                other = edge.get('from_resource_id')
            else:
                continue
            if isinstance(other, str) and other:
                verified.append(other)
        if verified:
            evidence['verified_dependencies'] = sorted(set(verified))
        evidence['dependency_inventory_complete'] = all(
            isinstance(e, dict) and e.get('verification_state') == 'verified' for e in refs
        )
    elif isinstance(refs, list) and not refs:
        evidence.setdefault('verified_dependencies', [])
        evidence['dependency_inventory_complete'] = True

    _set_number(evidence, 'burst_credit_balance_min', _series_minimum(evidence, 'burst_credits') or _summary_stat(evidence, 'burst_credits', 'minimum'))
    _set_number(
        evidence,
        'disk_queue_length_p99',
        _series_p99(evidence, 'disk_queue') or _series_p99(evidence, 'iops') or _summary_stat(evidence, 'disk_queue', 'p99'),
    )
    throttling = _metric_summary(evidence, 'throttling') or _metric_summary(evidence, 'cpu_percent')
    if throttling and type(throttling.get('p95')) in (int, float):
        _set_number(evidence, 'cfs_throttling_p95_pct', float(throttling['p95']) * 100 if throttling['p95'] <= 1 else float(throttling['p95']))
    elif _summary_stat(evidence, 'cpu_percent', 'p95') is not None:
        p95 = _summary_stat(evidence, 'cpu_percent', 'p95')
        _set_number(evidence, 'cfs_throttling_p95_pct', p95 * 100 if p95 <= 1 else p95)

    if not isinstance(evidence.get('state_history'), list):
        label = None
        if rtype == 'microsoft.web/serverfarms' and type(evidence.get('hosted_app_count')) is int:
            label = f'HostedSites/{evidence["hosted_app_count"]}'
        elif isinstance(evidence.get('power_state'), str) and evidence['power_state']:
            label = evidence['power_state']
        elif isinstance(evidence.get('disk_state'), str) and evidence['disk_state']:
            label = evidence['disk_state']
        created = moment(evidence.get('created_at'))
        if label and created:
            now_ts = datetime.now(timezone.utc)
            if created < now_ts:
                evidence['state_history'] = [
                    dict(state=label, start=created.isoformat(), end=now_ts.isoformat(), complete=True),
                ]

    return resource
