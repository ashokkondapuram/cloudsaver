"""Derive assessment-ready evidence from collected configuration, graph, and telemetry."""
from __future__ import annotations

import math
from typing import Any


def _set_bool(evidence: dict, key: str, value: bool | None) -> None:
    if value is None or key in evidence and isinstance(evidence[key], bool):
        return
    evidence[key] = value


def _set_number(evidence: dict, key: str, value: Any) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return
    if key not in evidence:
        evidence[key] = int(value) if type(value) is int or value == int(value) else value


def _rollup_utilization(evidence: dict) -> None:
    from app.evidence_metric_utilization import metric_window

    for key in (
        'cpu_percent',
        'memory_percent',
        'iops',
        'throughput',
        'normalized_ru_consumption',
        'ptu_utilization',
        'requests',
    ):
        source = metric_window(evidence, key)
        if not source:
            continue
        metrics = evidence.get('metrics') or {}
        series = metrics.get(key) if isinstance(metrics.get(key), dict) else {}
        if evidence.get('p95_usage') is None and source.get('p95') is not None:
            _set_number(evidence, 'p95_usage', source['p95'])
        if evidence.get('window_start') is None and series.get('window_start'):
            evidence['window_start'] = series['window_start']
        if evidence.get('window_end') is None and series.get('window_end'):
            evidence['window_end'] = series['window_end']
        if evidence.get('samples') is None and series.get('points'):
            _set_number(evidence, 'samples', len(series['points']))
        if evidence.get('step_seconds') is None and series.get('step_seconds') is not None:
            _set_number(evidence, 'step_seconds', series['step_seconds'])
        elif evidence.get('step_seconds') is None:
            evidence['step_seconds'] = 300
        if evidence.get('window_days') is None:
            evidence['window_days'] = 30
        evidence.setdefault('dimension', key)
        evidence.setdefault('unit', 'percent' if 'percent' in key else 'count')
        evidence.setdefault('percentile_method', 'P95')
        break


def _public_network_access(props: dict) -> bool | None:
    network = props.get('network')
    if isinstance(network, dict):
        access = network.get('publicNetworkAccess')
        if access == 'Enabled':
            return True
        if access == 'Disabled':
            return False
    access = props.get('publicNetworkAccess')
    if access == 'Enabled':
        return True
    if access == 'Disabled':
        return False
    return None


def project_configuration_properties(resource: dict, props: dict) -> None:
    """Map ARM/ARG properties into registry evidence fields not yet set."""
    if not isinstance(props, dict):
        return
    evidence = resource.setdefault('evidence', {})
    rtype = (resource.get('resource_type') or '').lower()
    arm_doc = evidence.get('arm_document') if isinstance(evidence.get('arm_document'), dict) else {}
    if isinstance(arm_doc.get('tags'), dict) and not evidence.get('tags'):
        evidence['tags'] = arm_doc['tags']

    if rtype == 'microsoft.network/loadbalancers':
        pools = props.get('backendAddressPools')
        if isinstance(pools, list):
            if evidence.get('backend_pool_count') is None:
                evidence['backend_pool_count'] = len(pools)
            if evidence.get('dependencies_verified') is None:
                evidence['dependencies_verified'] = len(pools) > 0
    elif rtype == 'microsoft.network/natgateways':
        subnet = props.get('subnet')
        if evidence.get('routing_verified') is None:
            evidence['routing_verified'] = isinstance(subnet, dict) and bool(subnet.get('id'))
    elif rtype in ('microsoft.dbforpostgresql/flexibleservers', 'microsoft.dbformysql/flexibleservers'):
        public = _public_network_access(props)
        if public is not None:
            _set_bool(evidence, 'publicly_accessible', public)
        tls = props.get('version') or props.get('minimalTlsVersion')
        if props.get('minimalTlsVersion') in ('TLS1_2', 'TLS1_3', '1.2', '1.3'):
            _set_bool(evidence, 'tls_required', True)
    elif rtype == 'microsoft.sql/servers/databases':
        public = _public_network_access(props)
        if public is not None:
            _set_bool(evidence, 'publicly_accessible', public)
    elif rtype == 'microsoft.synapse/workspaces':
        public = _public_network_access(props)
        if public is not None:
            _set_bool(evidence, 'publicly_accessible', public)
    elif rtype == 'microsoft.cognitiveservices/accounts':
        sku = props.get('sku') or arm_doc.get('sku') or {}
        if isinstance(sku, dict):
            name = (sku.get('name') or '').lower()
            if 'ptu' in name or sku.get('tier') == 'ProvisionedManaged':
                evidence['provisioned_mode'] = True
            elif name:
                evidence.setdefault('provisioned_mode', False)
    elif rtype == 'microsoft.containerinstance/containergroups':
        state = props.get('instanceView', {}).get('state') if isinstance(props.get('instanceView'), dict) else props.get('provisioningState')
        if isinstance(state, str) and evidence.get('power_state') is None:
            evidence['power_state'] = state
    elif rtype == 'microsoft.network/applicationgateways':
        pools = props.get('backendAddressPools')
        if isinstance(pools, list) and evidence.get('backend_pool_count') is None:
            evidence['backend_pool_count'] = len(pools)
        op = props.get('operationalState')
        if isinstance(op, str):
            evidence['operational_state'] = op
        if evidence.get('dependencies_verified') is None and isinstance(pools, list):
            evidence['dependencies_verified'] = len(pools) > 0
    elif rtype == 'microsoft.compute/virtualmachinescalesets':
        vm_profile = props.get('virtualMachineProfile') or {}
        hardware = vm_profile.get('hardwareProfile') or {}
        if isinstance(hardware.get('vmSize'), str):
            evidence.setdefault('vm_size', hardware['vmSize'])
        if evidence.get('power_state') is None and isinstance(props.get('provisioningState'), str):
            evidence['power_state'] = props['provisioningState']


def autofill_evidence(resource: dict) -> dict:
    evidence = resource.setdefault('evidence', {})
    if evidence.get('dependency_inventory_complete') is True:
        _set_bool(evidence, 'dependencies_verified', True)

    tags = evidence.get('tags') or evidence.get('labels') or {}
    if isinstance(tags, dict):
        for key, value in tags.items():
            if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
                continue
            if key.casefold() in ('owner', 'owneremail', 'technical_owner', 'business_owner', 'application', 'applicationid'):
                evidence.setdefault('ownership_tag_present', True)
                break

    if evidence.get('operational_state') is None:
        for field in ('power_state', 'disk_state', 'provisioning_state'):
            if isinstance(evidence.get(field), str) and evidence[field]:
                evidence['operational_state'] = evidence[field]
                break

    if evidence.get('backend_pool_count') is None and type(evidence.get('load_balancer_backend_count')) is int:
        evidence['backend_pool_count'] = evidence['load_balancer_backend_count']

    if type(evidence.get('allow_blob_public_access')) is bool and evidence.get('public_snapshot') is None:
        evidence['public_snapshot'] = evidence['allow_blob_public_access']

    _rollup_utilization(evidence)
    from app.evidence_metric_utilization import apply_metrics_to_evidence_fields

    apply_metrics_to_evidence_fields(evidence)
    return resource
