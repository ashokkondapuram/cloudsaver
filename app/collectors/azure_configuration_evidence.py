"""Project Azure inventory and ARM configuration into analysis-ready evidence fields."""
from __future__ import annotations

import math
from typing import Any, Callable

from app.resource_catalog import family

# Rules that require Azure Monitor / Activity Log (not satisfied by configuration alone).
TELEMETRY_RULE_IDS = frozenset({
    'AZURE_DISK_PROVISIONED_PERFORMANCE',
    'AZURE_PUBLIC_IP_ASSOCIATED_IDLE',
    'AZURE_VM_RIGHTSIZING_UTILIZATION',
    'AZURE_ASP_UNDERUTILIZED_SKU',
})

_ENCRYPTION_VALUES = frozenset({
    'EncryptionAtRestWithPlatformKey',
    'EncryptionAtRestWithCustomerKey',
    'EncryptionAtRestWithPlatformAndCustomerKeys',
})
_TLS_VALUES = frozenset({'1.2', '1.3', 'TLS1_2', 'TLS1_3'})


def _get(mapping: dict, *path: str) -> Any:
    value = mapping
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _set_bool(evidence: dict, key: str, value: bool | None) -> None:
    if value is None or key in evidence and isinstance(evidence[key], bool):
        return
    evidence[key] = value


def _set_number(evidence: dict, key: str, value: Any) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return
    if key not in evidence:
        evidence[key] = int(value) if type(value) is int or value == int(value) else value


def _set_text(evidence: dict, key: str, value: Any) -> None:
    if isinstance(value, str) and value and key not in evidence:
        evidence[key] = value


def _public_ip_association(props: dict) -> bool | None:
    ip_cfg = props.get('ipConfiguration')
    nat = props.get('natGateway')
    has_nic = isinstance(ip_cfg, dict) and bool(ip_cfg.get('id'))
    has_nat = isinstance(nat, dict) and bool(nat.get('id'))
    if has_nic or has_nat:
        return True
    if ip_cfg is not None or nat is not None:
        return False
    return None


def _disk_target(props: dict, evidence: dict) -> None:
    iops = props.get('diskIOPSReadWrite') or evidence.get('provisioned_iops')
    mbps = props.get('diskMBpsReadWrite')
    if type(iops) in (int, float) and iops > 0 and type(mbps) in (int, float) and mbps > 0:
        evidence.setdefault('target_disk', {})
        evidence['target_disk'].setdefault('iops', int(iops))
        evidence['target_disk'].setdefault('throughput', int(mbps * 1024 * 1024))


def _apply_type_contract(resource: dict, props: dict) -> tuple[int, int]:
    """Merge configuration properties into top-level evidence; return (observed, total) field counts."""
    rtype = (resource.get('resource_type') or '').lower()
    evidence = resource.setdefault('evidence', {})
    observed = 0
    total = 0

    def want(key: str, present: bool) -> None:
        nonlocal observed, total
        total += 1
        if present:
            observed += 1

    if rtype == 'microsoft.compute/disks':
        state = props.get('diskState') or evidence.get('disk_state')
        _set_text(evidence, 'disk_state', state)
        want('disk_state', isinstance(evidence.get('disk_state'), str))
        _set_number(evidence, 'size_gb', props.get('diskSizeGB') or evidence.get('size_gb'))
        _set_number(evidence, 'provisioned_iops', props.get('diskIOPSReadWrite') or evidence.get('provisioned_iops'))
        want('size_gb', type(evidence.get('size_gb')) is int)
        enc = props.get('encryption')
        if isinstance(enc, dict) and enc.get('type') in _ENCRYPTION_VALUES:
            _set_bool(evidence, 'encrypted', True)
        want('encrypted', isinstance(evidence.get('encrypted'), bool))
        _disk_target(props, evidence)
        want('target_disk', bool((evidence.get('target_disk') or {}).get('iops')))
    elif rtype == 'microsoft.compute/virtualmachines':
        power = evidence.get('power_state')
        if not power:
            extended = props.get('extended') or {}
            view = extended.get('instanceView') if isinstance(extended, dict) else {}
            code = (view.get('powerState') or {}).get('code') if isinstance(view, dict) else None
            _set_text(evidence, 'power_state', code)
        want('power_state', isinstance(evidence.get('power_state'), str))
        _set_text(evidence, 'vm_size', _get(props, 'hardwareProfile', 'vmSize') or evidence.get('vm_size'))
        want('vm_size', isinstance(evidence.get('vm_size'), str))
    elif rtype == 'microsoft.network/publicipaddresses':
        assoc = _public_ip_association(props)
        if assoc is not None:
            evidence['association_verified'] = assoc
        want('association_verified', isinstance(evidence.get('association_verified'), bool))
    elif rtype == 'microsoft.web/serverfarms':
        sites = props.get('numberOfSites')
        if type(sites) is int and sites >= 0:
            evidence['hosted_app_count'] = sites
        _set_text(evidence, 'sku_tier', _get(props, 'sku', 'tier') or evidence.get('sku_tier'))
        _set_text(evidence, 'sku_name', _get(props, 'sku', 'name') or evidence.get('sku_name'))
        want('hosted_app_count', type(evidence.get('hosted_app_count')) is int)
        want('sku_tier', isinstance(evidence.get('sku_tier'), str))
    elif rtype == 'microsoft.web/sites':
        _set_text(evidence, 'sku_name', evidence.get('sku_name'))
        state = props.get('state')
        if isinstance(state, str):
            evidence['site_state'] = state
    elif rtype == 'microsoft.storage/storageaccounts':
        if type(props.get('allowBlobPublicAccess')) is bool:
            _set_bool(evidence, 'allow_blob_public_access', props['allowBlobPublicAccess'])
        if props.get('supportsHttpsTrafficOnly') is True:
            _set_bool(evidence, 'supports_https_traffic_only', True)
        tls = props.get('minimumTlsVersion')
        if tls in _TLS_VALUES:
            evidence['tls_required'] = True
        enc = props.get('encryption')
        if isinstance(enc, dict) and enc.get('keySource'):
            _set_bool(evidence, 'encrypted', True)
        want('encrypted', isinstance(evidence.get('encrypted'), bool))
        want('tls_required', isinstance(evidence.get('tls_required'), bool))
        want('allow_blob_public_access', isinstance(evidence.get('allow_blob_public_access'), bool))
        want('lifecycle_policy_verified', isinstance(evidence.get('lifecycle_policy_verified'), bool))
    elif rtype == 'microsoft.dbforpostgresql/flexibleservers':
        _set_number(evidence, 'backup_retention_days', _get(props, 'backup', 'backupRetentionDays'))
        ha = props.get('highAvailability')
        if isinstance(ha, dict) and ha.get('mode') not in (None, 'Disabled'):
            _set_bool(evidence, 'multi_az', True)
        elif isinstance(ha, dict) and ha.get('mode') == 'Disabled':
            _set_bool(evidence, 'multi_az', False)
        want('backup_retention_days', type(evidence.get('backup_retention_days')) is int)
    elif rtype == 'microsoft.sql/servers/databases':
        _set_bool(evidence, 'multi_az', props.get('zoneRedundant') if type(props.get('zoneRedundant')) is bool else None)
        want('multi_az', isinstance(evidence.get('multi_az'), bool))
    elif rtype == 'microsoft.cache/redis':
        tls = props.get('minimumTlsVersion')
        if tls in _TLS_VALUES:
            evidence['tls_required'] = True
        want('tls_required', isinstance(evidence.get('tls_required'), bool))
    elif rtype == 'microsoft.containerservice/managedclusters':
        _set_text(evidence, 'kubernetes_version', props.get('kubernetesVersion') or evidence.get('kubernetes_version'))
        code = _get(props, 'powerState', 'code')
        _set_text(evidence, 'power_state', code or evidence.get('power_state'))
        want('kubernetes_version', isinstance(evidence.get('kubernetes_version'), str))

    return observed, max(total, 1)


def telemetry_rules_for(resource: dict) -> list[str]:
    row = family(resource)
    if not row or row[0] != 'azure':
        return []
    return [rule_id for rule_id in row[4] if rule_id in TELEMETRY_RULE_IDS]


def enrich_configuration_evidence(resource: dict) -> dict:
    """Normalize configuration into evidence fields used by assessment and analysis rules."""
    evidence = resource.setdefault('evidence', {})
    props = evidence.get('typed_configuration')
    if not isinstance(props, dict):
        props = {}
    observed, total = _apply_type_contract(resource, props)
    if evidence.get('typed_configuration'):
        evidence['evidence_schema_version'] = '3'
    elif evidence.get('source') == 'Azure Resource Graph':
        evidence.setdefault('evidence_schema_version', '2')
    pending = telemetry_rules_for(resource)
    satisfied = set()
    for rule_id in list(pending):
        satisfied |= _telemetry_satisfied(resource, rule_id)
    pending = [rule_id for rule_id in pending if rule_id not in satisfied]
    evidence['analysis_readiness'] = dict(
        configuration='complete' if observed >= total else 'partial' if observed else 'missing',
        configuration_observed=observed,
        configuration_total=total,
        telemetry_pending_rule_ids=pending,
    )
    resource['unsupported_rule_ids'] = pending
    return resource


def _telemetry_satisfied(resource: dict, rule_id: str) -> set[str]:
    evidence = resource.get('evidence') or {}
    metrics = evidence.get('metrics') or {}
    if rule_id == 'AZURE_DISK_PROVISIONED_PERFORMANCE':
        return {rule_id} if metrics.get('iops') and metrics.get('throughput') else set()
    if rule_id == 'AZURE_PUBLIC_IP_ASSOCIATED_IDLE':
        return {rule_id} if metrics.get('ingress_bytes') else set()
    if rule_id in ('AZURE_VM_RIGHTSIZING_UTILIZATION', 'AZURE_ASP_UNDERUTILIZED_SKU'):
        return {rule_id} if metrics.get('cpu_percent') and metrics.get('memory_percent') else set()
    return set()


def enrich_inventory_configuration(inventory: list[dict]) -> list[dict]:
    for resource in inventory:
        enrich_configuration_evidence(resource)
    return inventory


def live_collection_priority(resource: dict) -> tuple:
    """Prefer resources that still owe telemetry for analysis rules."""
    pending = len((resource.get('evidence') or {}).get('analysis_readiness', {}).get('telemetry_pending_rule_ids') or [])
    arm = (resource.get('evidence') or {}).get('arm_detail') == 'collected'
    return (-pending, -int(arm), resource.get('resource_id') or '')
