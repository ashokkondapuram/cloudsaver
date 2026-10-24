"""Published Azure review configuration; keep in sync with CloudSaver's evidence contracts."""
DEFINITIONS = (
    ('AZURE_DISK_UNATTACHED_RETENTION', 'storage', 'microsoft.compute/disks', 'Retained unattached disk review', {'minimum_days': (14, 7, 90)}),
    ('AZURE_DISK_PROVISIONED_PERFORMANCE', 'storage', 'microsoft.compute/disks', 'Disk recovery and performance review', {'headroom_percent': (30, 20, 100)}),
    ('AZURE_PUBLIC_IP_UNASSOCIATED', 'network', 'microsoft.network/publicipaddresses', 'Unassociated public IP review', {'minimum_days': (7, 7, 90)}),
    ('AZURE_PUBLIC_IP_ASSOCIATED_IDLE', 'network', 'microsoft.network/publicipaddresses', 'Associated public IP traffic review', {'maximum_bytes': (0, 0, 1024)}),
    ('AZURE_VM_STOPPED_RESIDUAL_COST', 'compute', 'microsoft.compute/virtualmachines', 'Stopped VM residual charge review', {'minimum_days': (14, 7, 90)}),
    ('AZURE_VM_RIGHTSIZING_UTILIZATION', 'compute', 'microsoft.compute/virtualmachines', 'Evidence-based VM rightsizing review', {'cpu_percent': (10, 1, 20)}),
    ('AZURE_ASP_EMPTY_PAID_PLAN', 'application', 'microsoft.web/serverfarms', 'Empty paid App Service plan review', {'minimum_days': (7, 7, 90)}),
    ('AZURE_ASP_UNDERUTILIZED_SKU', 'application', 'microsoft.web/serverfarms', 'App Service capacity review', {'cpu_percent': (15, 1, 30), 'memory_percent': (30, 1, 40)}),
)
BOUNDS = {row[0]: row[4] for row in DEFINITIONS}


def validate_parameters(rule_id, supplied):
    bounds = BOUNDS.get(rule_id, {})
    if not isinstance(supplied, dict) or set(supplied) - set(bounds):
        raise ValueError('Unsupported rule parameter')
    for key, value in supplied.items():
        if type(value) is not int or not bounds[key][1] <= value <= bounds[key][2]:
            raise ValueError('Rule parameter is outside delegated bounds')
    return dict(supplied)
