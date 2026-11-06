"""Project Azure inventory and ARM configuration into analysis-ready evidence fields."""
from __future__ import annotations

import math
from typing import Any, Callable

from app.azure_resource_registry import telemetry_rules_for_resource, telemetry_satisfied, type_registry_summary

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
    elif rtype == 'microsoft.network/networkinterfaces':
        vm = props.get('virtualMachine')
        pe = props.get('privateEndpoint')
        has_vm = isinstance(vm, dict) and bool(vm.get('id'))
        has_pe = isinstance(pe, dict) and bool(pe.get('id'))
        if has_vm or has_pe:
            evidence['association_verified'] = True
            evidence['nic_orphaned'] = False
        elif props:
            evidence['association_verified'] = False
            evidence['nic_orphaned'] = True
        want('nic_orphaned', isinstance(evidence.get('nic_orphaned'), bool))
    elif rtype == 'microsoft.network/networksecuritygroups':
        nics = props.get('networkInterfaces') or []
        subnets = props.get('subnets') or []
        if isinstance(nics, list) and isinstance(subnets, list):
            evidence['nsg_nic_count'] = len(nics)
            evidence['nsg_subnet_count'] = len(subnets)
            evidence['nsg_orphaned'] = not nics and not subnets
        want('nsg_orphaned', isinstance(evidence.get('nsg_orphaned'), bool))
    elif rtype == 'microsoft.web/serverfarms':
        sites = props.get('numberOfSites')
        if type(sites) is int and sites >= 0:
            evidence['hosted_app_count'] = sites
        if props.get('httpsOnly') is True:
            _set_bool(evidence, 'https_only', True)
        elif props.get('httpsOnly') is False:
            _set_bool(evidence, 'https_only', False)
        _set_text(evidence, 'sku_tier', _get(props, 'sku', 'tier') or evidence.get('sku_tier'))
        _set_text(evidence, 'sku_name', _get(props, 'sku', 'name') or evidence.get('sku_name'))
        want('hosted_app_count', type(evidence.get('hosted_app_count')) is int)
        want('sku_tier', isinstance(evidence.get('sku_tier'), str))
    elif rtype == 'microsoft.web/sites':
        _set_text(evidence, 'sku_name', evidence.get('sku_name'))
        state = props.get('state')
        if isinstance(state, str):
            evidence['site_state'] = state
        site_config = props.get('siteConfig') if isinstance(props.get('siteConfig'), dict) else {}
        if site_config.get('healthCheckPath'):
            _set_bool(evidence, 'health_probes_enabled', True)
            paths = evidence.get('health_check_paths')
            if not isinstance(paths, list):
                evidence['health_check_paths'] = [site_config['healthCheckPath']]
        elif site_config.get('alwaysOn') is False:
            _set_bool(evidence, 'health_probes_enabled', False)
        if props.get('httpsOnly') is True:
            _set_bool(evidence, 'https_only', True)
        settings = site_config.get('appSettings') or []
        if any(isinstance(s, dict) and '@Microsoft.KeyVault' in str(s.get('value', '')) for s in settings):
            _set_bool(evidence, 'managed_secrets', True)
        if type(props.get('keyVaultReferenceIdentity')) is str and props['keyVaultReferenceIdentity']:
            _set_bool(evidence, 'managed_secrets', True)
        want('health_probes_enabled', isinstance(evidence.get('health_probes_enabled'), bool))
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
    elif rtype == 'microsoft.dbformysql/flexibleservers':
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
    elif rtype == 'microsoft.documentdb/databaseaccounts':
        caps = props.get('capabilities') or []
        if any(isinstance(c, dict) and c.get('name') == 'EnableServerless' for c in caps):
            evidence['manual_throughput'] = False
        elif props.get('enableFreeTier') is False:
            evidence.setdefault('manual_throughput', True)
        want('manual_throughput', isinstance(evidence.get('manual_throughput'), bool))
    elif rtype == 'microsoft.network/applicationgateways':
        pools = props.get('backendAddressPools')
        if isinstance(pools, list):
            evidence['backend_pool_count'] = len(pools)
        _set_text(evidence, 'operational_state', props.get('operationalState') or evidence.get('operational_state'))
        want('backend_pool_count', type(evidence.get('backend_pool_count')) is int)
    elif rtype == 'microsoft.servicebus/namespaces':
        if type(props.get('disableLocalAuth')) is bool:
            evidence['disable_local_auth'] = props['disableLocalAuth']
        want('disable_local_auth', isinstance(evidence.get('disable_local_auth'), bool))
    elif rtype == 'microsoft.eventhub/namespaces':
        if type(props.get('disableLocalAuth')) is bool:
            evidence['disable_local_auth'] = props['disableLocalAuth']
        want('disable_local_auth', isinstance(evidence.get('disable_local_auth'), bool))
    elif rtype == 'microsoft.keyvault/vaults':
        if props.get('enableRbacAuthorization') is True:
            _set_bool(evidence, 'encrypted', True)
        pna = props.get('publicNetworkAccess')
        if isinstance(pna, str):
            evidence['public_network_access'] = pna
        want('encrypted', isinstance(evidence.get('encrypted'), bool))

    return observed, max(total, 1)


def telemetry_rules_for(resource: dict) -> list[str]:
    if resource.get('cloud_provider', 'azure') != 'azure':
        return []
    return telemetry_rules_for_resource(resource)


def _hydrate_typed_configuration(resource: dict) -> dict:
    """Rebuild typed_configuration from ARG flat evidence when ARM detail was not fetched."""
    evidence = resource.setdefault('evidence', {})
    snapshot = resource.get('configuration_snapshot')
    if isinstance(snapshot, dict):
        for key, value in snapshot.items():
            if key in ('metrics', 'state_history', 'typed_configuration', 'arm_document'):
                continue
            if evidence.get(key) is None and value is not None:
                evidence[key] = value
    existing = evidence.get('typed_configuration')
    if isinstance(existing, dict) and existing:
        return existing
    rtype = (resource.get('resource_type') or '').lower()
    built: dict[str, Any] = {}
    if rtype == 'microsoft.compute/disks':
        for flat, typed_key in (
            ('disk_state', 'diskState'),
            ('size_gb', 'diskSizeGB'),
            ('provisioned_iops', 'diskIOPSReadWrite'),
        ):
            if evidence.get(flat) is not None:
                built[typed_key] = evidence[flat]
        if evidence.get('encrypted') is True:
            built.setdefault('encryption', {})['type'] = 'EncryptionAtRestWithPlatformKey'
    elif rtype == 'microsoft.compute/virtualmachines':
        if evidence.get('vm_size'):
            built.setdefault('hardwareProfile', {})['vmSize'] = evidence['vm_size']
        if evidence.get('power_state'):
            built.setdefault('extended', {})['instanceView'] = {'powerState': {'code': evidence['power_state']}}
    elif rtype == 'microsoft.web/serverfarms':
        if type(evidence.get('hosted_app_count')) is int:
            built['numberOfSites'] = evidence['hosted_app_count']
        if evidence.get('sku_name') or evidence.get('sku_tier'):
            built['sku'] = {
                **({'name': evidence['sku_name']} if evidence.get('sku_name') else {}),
                **({'tier': evidence['sku_tier']} if evidence.get('sku_tier') else {}),
            }
    elif rtype == 'microsoft.storage/storageaccounts':
        for flat, typed_key in (
            ('allow_blob_public_access', 'allowBlobPublicAccess'),
            ('supports_https_traffic_only', 'supportsHttpsTrafficOnly'),
        ):
            if type(evidence.get(flat)) is bool:
                built[typed_key] = evidence[flat]
        if evidence.get('tls_required') is True:
            built['minimumTlsVersion'] = 'TLS1_2'
        if evidence.get('encrypted') is True:
            built.setdefault('encryption', {})['keySource'] = 'Microsoft.Storage'
    elif rtype == 'microsoft.network/publicipaddresses':
        if type(evidence.get('association_verified')) is bool:
            if evidence['association_verified']:
                built['ipConfiguration'] = {'id': 'linked'}
            else:
                built['ipConfiguration'] = None
                built['natGateway'] = None
    elif rtype == 'microsoft.network/networkinterfaces':
        vm = evidence.get('nic_vm_id') or evidence.get('virtual_machine_id')
        pe = evidence.get('nic_private_endpoint_id')
        if isinstance(vm, str) and vm:
            built['virtualMachine'] = {'id': vm}
        elif isinstance(pe, str) and pe:
            built['privateEndpoint'] = {'id': pe}
        elif evidence.get('nic_orphaned') is True:
            built['virtualMachine'] = None
            built['privateEndpoint'] = None
    elif rtype == 'microsoft.network/networksecuritygroups':
        if type(evidence.get('nsg_subnet_count')) is int:
            built['subnets'] = [{}] * evidence['nsg_subnet_count']
        if type(evidence.get('nsg_nic_count')) is int:
            built['networkInterfaces'] = [{}] * evidence['nsg_nic_count']
    elif rtype == 'microsoft.network/loadbalancers':
        count = evidence.get('backend_pool_count')
        if type(count) is int and count >= 0:
            built['backendAddressPools'] = [{}] * count
    elif rtype == 'microsoft.network/applicationgateways':
        count = evidence.get('backend_pool_count')
        if type(count) is int and count >= 0:
            built['backendAddressPools'] = [{}] * count
        if isinstance(evidence.get('operational_state'), str):
            built['operationalState'] = evidence['operational_state']
    if built:
        evidence['typed_configuration'] = built
    return evidence.get('typed_configuration') or {}


def enrich_configuration_evidence(resource: dict) -> dict:
    """Normalize configuration into evidence fields used by assessment and analysis rules."""
    evidence = resource.setdefault('evidence', {})
    props = _hydrate_typed_configuration(resource)
    from app.evidence_autofill import project_configuration_properties

    project_configuration_properties(resource, props)
    observed, total = _apply_type_contract(resource, props)
    if evidence.get('typed_configuration'):
        evidence['evidence_schema_version'] = '3'
    elif evidence.get('source') == 'Azure Resource Graph':
        evidence.setdefault('evidence_schema_version', '2')
    from app.evidence_derived_facts import apply_derived_facts
    from app.evidence_autofill import autofill_evidence

    apply_derived_facts(resource)
    autofill_evidence(resource)
    pending = [rule_id for rule_id in telemetry_rules_for(resource) if not telemetry_satisfied(rule_id, evidence)]
    summary = type_registry_summary(resource)
    evidence['type_registry'] = summary
    pending_fields = summary.get('evidence_fields_pending') or []
    evidence['analysis_readiness'] = dict(
        configuration='complete' if not pending_fields else 'partial' if observed else 'missing',
        configuration_observed=observed,
        configuration_total=total,
        telemetry_pending_rule_ids=pending,
    )
    resource['unsupported_rule_ids'] = pending
    return resource


def _telemetry_satisfied(resource: dict, rule_id: str) -> set[str]:
    evidence = resource.get('evidence') or {}
    if telemetry_satisfied(rule_id, evidence):
        return {rule_id}
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
