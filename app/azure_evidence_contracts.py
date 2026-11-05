"""Azure evidence contract bounds aligned with the platform identity contracts module."""

from app.resource_catalog import RULE_DISPLAY_NAMES, definitions

_AZURE_CONTRACT_BOUNDS = {
    'AZURE_DISK_UNATTACHED_RETENTION': {'minimum_days': (14, 7, 90)},
    'AZURE_DISK_PROVISIONED_PERFORMANCE': {'headroom_percent': (30, 20, 100)},
    'AZURE_PUBLIC_IP_UNASSOCIATED': {'minimum_days': (7, 7, 90)},
    'AZURE_PUBLIC_IP_ASSOCIATED_IDLE': {'maximum_bytes': (0, 0, 1024)},
    'AZURE_VM_STOPPED_RESIDUAL_COST': {'minimum_days': (14, 7, 90)},
    'AZURE_VM_RIGHTSIZING_UTILIZATION': {'cpu_percent': (10, 1, 20)},
    'AZURE_ASP_EMPTY_PAID_PLAN': {'minimum_days': (7, 7, 90)},
    'AZURE_ASP_UNDERUTILIZED_SKU': {'cpu_percent': (15, 1, 30), 'memory_percent': (30, 1, 40)},
}
_AZURE_EVIDENCE_TYPE_SUFFIX = {
    'AZURE_DISK_UNATTACHED_RETENTION': 'disks',
    'AZURE_DISK_PROVISIONED_PERFORMANCE': 'disks',
    'AZURE_PUBLIC_IP_UNASSOCIATED': 'publicipaddresses',
    'AZURE_PUBLIC_IP_ASSOCIATED_IDLE': 'publicipaddresses',
    'AZURE_VM_STOPPED_RESIDUAL_COST': 'virtualmachines',
    'AZURE_VM_RIGHTSIZING_UTILIZATION': 'virtualmachines',
    'AZURE_ASP_EMPTY_PAID_PLAN': 'serverfarms',
    'AZURE_ASP_UNDERUTILIZED_SKU': 'serverfarms',
}

AZURE_EVIDENCE_CONTRACT_IDS = frozenset(_AZURE_CONTRACT_BOUNDS)


def azure_evidence_contract(rule_id: str):
    """Return (rule_id, arm_type_suffix, display_name, parameter_bounds) for contract unit tests."""
    return (
        rule_id,
        _AZURE_EVIDENCE_TYPE_SUFFIX[rule_id],
        RULE_DISPLAY_NAMES[rule_id],
        dict(_AZURE_CONTRACT_BOUNDS[rule_id]),
    )


def azure_evidence_contracts():
    return tuple(azure_evidence_contract(rid) for rid in sorted(AZURE_EVIDENCE_CONTRACT_IDS))


def rule_resource_type_suffix(rule_id: str) -> str | None:
    return _AZURE_EVIDENCE_TYPE_SUFFIX.get(rule_id)


def validate_rule_parameters(rule_id, overrides=None):
    if rule_id in _AZURE_CONTRACT_BOUNDS:
        bounds = _AZURE_CONTRACT_BOUNDS[rule_id]
    else:
        bounds = {row[0]: row[6] for row in definitions()}.get(rule_id)
        if bounds is None:
            raise ValueError('Unknown rule parameter')
    if not isinstance(overrides or {}, dict) or set(overrides or {}) - set(bounds):
        raise ValueError('Unknown rule parameter')
    result = {}
    for key, (default, low, high) in bounds.items():
        value = (overrides or {}).get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
        result[key] = value
    return result
