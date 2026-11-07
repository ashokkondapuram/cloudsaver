"""Which pillar checks and telemetry apply to each catalog resource type."""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

from app.resource_catalog import FAMILIES, family

# Every assessed resource gets these; gaps here always surface in the drawer.
BASELINE: FrozenSet[str] = frozenset(
    {
        'RETAIL_ESTIMATE',
        'BILLED_COST',
        'COMMITMENT_LOCK',
        'OWNERSHIP',
        'DEPENDENCY_GRAPH',
        'OBSERVATION_FRESHNESS',
        'PROTECTION_METADATA',
        'MANAGEMENT_LOCK',
        'STATE_TRANSITION_AUDIT',
        'PROTECTED_INTENT',
    }
)

# Performance numeric thresholds (code -> evidence field) by family.
_PERF_VM = frozenset({'CFS_THROTTLING', 'BURST_CREDITS', 'SURPLUS_CREDITS', 'SLO_BURN'})
_PERF_DISK = frozenset({'DISK_QUEUE', 'BURST_CREDITS'})
_PERF_ASP = frozenset({'CFS_THROTTLING', 'SERVICE_THROTTLING'})
_PERF_GATEWAY = frozenset({'HTTP_THROTTLING', 'SLO_BURN'})
_PERF_DATA = frozenset({'CFS_THROTTLING', 'REPLICATION_LAG'})

_UTIL_STANDARD = frozenset({'UTILIZATION_WINDOW', 'FIVE_MINUTE_UTILIZATION', 'REQUEST_HEADROOM'})
_UTIL_COMPUTE = _UTIL_STANDARD | frozenset({'SLO_LATENCY_CORRELATION', 'OBSERVED_LATENCY_SENSITIVITY'})
_UTIL_DATA = _UTIL_STANDARD | frozenset({'SLO_LATENCY_CORRELATION'})

_SECURITY_ENCRYPT = frozenset({'ENCRYPTION_AT_REST', 'CUSTOMER_MANAGED_KEY'})
_SECURITY_DB = frozenset({'PUBLIC_DATABASE', 'DATABASE_TLS', 'ENGINE_SUPPORT', 'AUTO_MINOR_UPGRADE'})
_SECURITY_APP = frozenset({'HEALTH_PROBES', 'MANAGED_SECRETS', 'TRANSPORT_TLS'})
_SECURITY_NET = frozenset({'FLOW_LOGS'})
_SECURITY_STORAGE = frozenset({'SNAPSHOT_EXPOSURE'})

_RELIABILITY_HA = frozenset({'FAILOVER_TOPOLOGY', 'MULTI_AZ_INTENT'})
_RELIABILITY_DB = frozenset({'DATABASE_RECOVERY', 'BACKUP_RETENTION'})
_RELIABILITY_SNAP = frozenset({'SNAPSHOT_VERIFICATION', 'SNAPSHOT_FRESHNESS', 'RECOVERY_SNAPSHOT'})

_COST_DISK = frozenset({'UNATTACHED_DURATION'})
_COST_APP = frozenset({'APPLICATION_DENSITY'})

_OPS_COMPUTE = frozenset({'PATCH_CURRENCY', 'MONITORING_AGENT', 'ADMIN_INGRESS'})

# Catalog family id (FAMILIES[1]) -> allowed check codes.
FAMILY_CHECKS: dict[str, FrozenSet[str]] = {
    'managed-disks': BASELINE
    | _COST_DISK
    | _RELIABILITY_SNAP
    | _SECURITY_ENCRYPT
    | _SECURITY_STORAGE
    | frozenset({'PUBLIC_EXPOSURE'})
    | _UTIL_STANDARD
    | _PERF_DISK,
    'virtual-machines': BASELINE
    | _RELIABILITY_HA
    | _OPS_COMPUTE
    | frozenset({'ACCESS_AND_EXPOSURE', 'PUBLIC_EXPOSURE'})
    | _SECURITY_ENCRYPT
    | _UTIL_COMPUTE
    | _PERF_VM,
    'ip-nat': BASELINE
    | frozenset({'PUBLIC_EXPOSURE', 'ACCESS_AND_EXPOSURE'})
    | _UTIL_STANDARD
    | frozenset({'SERVICE_THROTTLING'}),
    'gateways': BASELINE
    | _RELIABILITY_HA
    | _SECURITY_NET
    | frozenset({'PUBLIC_EXPOSURE', 'ACCESS_AND_EXPOSURE'})
    | _UTIL_STANDARD
    | _PERF_GATEWAY,
    'app-service': BASELINE
    | _COST_APP
    | _RELIABILITY_HA
    | _SECURITY_APP
    | frozenset({'PUBLIC_EXPOSURE', 'APPLICATION_DENSITY'})
    | _UTIL_COMPUTE
    | _PERF_ASP,
    'sql-postgres': BASELINE
    | _RELIABILITY_HA
    | _RELIABILITY_DB
    | _SECURITY_DB
    | _SECURITY_ENCRYPT
    | _UTIL_DATA
    | _PERF_DATA,
    'cosmosdb': BASELINE
    | _RELIABILITY_HA
    | _SECURITY_DB
    | _SECURITY_ENCRYPT
    | _UTIL_DATA
    | _PERF_DATA,
    'redis': BASELINE
    | _RELIABILITY_HA
    | _SECURITY_DB
    | _SECURITY_ENCRYPT
    | _UTIL_DATA
    | _PERF_DATA,
    'blob-storage': BASELINE
    | _RELIABILITY_SNAP
    | _SECURITY_ENCRYPT
    | _SECURITY_STORAGE
    | frozenset({'PUBLIC_EXPOSURE'})
    | _UTIL_STANDARD,
    'ai-foundry': BASELINE
    | _RELIABILITY_HA
    | _SECURITY_ENCRYPT
    | frozenset({'KEYLESS_LOCAL_AUTH', 'MODEL_GUARDRAIL', 'PUBLIC_EXPOSURE', 'TRANSPORT_TLS'})
    | _UTIL_DATA
    | _PERF_DATA,
    'network-orphan': BASELINE | frozenset({'PUBLIC_EXPOSURE', 'FLOW_LOGS'}),
    'aks': BASELINE | _RELIABILITY_HA | _OPS_COMPUTE | frozenset({'ACCESS_AND_EXPOSURE', 'PUBLIC_EXPOSURE'}) | _UTIL_COMPUTE | _PERF_VM,
    'containers': BASELINE | _OPS_COMPUTE | frozenset({'ACCESS_AND_EXPOSURE', 'PUBLIC_EXPOSURE'}) | _UTIL_COMPUTE | _PERF_VM,
    'messaging': BASELINE | _SECURITY_ENCRYPT | _UTIL_STANDARD,
    'platform': BASELINE | _SECURITY_ENCRYPT | _UTIL_STANDARD,
    'integration': BASELINE | _SECURITY_APP | _UTIL_STANDARD,
    'analytics': BASELINE | _RELIABILITY_DB | _SECURITY_DB | _UTIL_DATA | _PERF_DATA,
    'compute-other': BASELINE | _OPS_COMPUTE | frozenset({'ACCESS_AND_EXPOSURE', 'PUBLIC_EXPOSURE'}) | _UTIL_COMPUTE | _PERF_VM,
    'network-other': BASELINE | _SECURITY_NET | frozenset({'PUBLIC_EXPOSURE', 'ACCESS_AND_EXPOSURE'}) | _UTIL_STANDARD,
    'application-other': BASELINE | _COST_APP | _SECURITY_APP | frozenset({'PUBLIC_EXPOSURE'}) | _UTIL_COMPUTE,
}

# Reuse Azure-shaped profiles for other providers in the v1.4 catalog.
for _alias, _source in (
    ('ebs', 'managed-disks'),
    ('persistent-disks', 'managed-disks'),
    ('s3', 'blob-storage'),
    ('ec2', 'virtual-machines'),
    ('gce', 'virtual-machines'),
    ('eip-nat', 'ip-nat'),
    ('load-balancers', 'gateways'),
    ('rds-aurora', 'sql-postgres'),
    ('sql-alloydb', 'sql-postgres'),
    ('dynamodb', 'cosmosdb'),
    ('elasticache', 'redis'),
    ('bigquery', 'cosmosdb'),
    ('lambda-ecs', 'app-service'),
    ('cloudrun-memorystore', 'app-service'),
    ('ai-inference', 'ai-foundry'),
    ('vertex-ai', 'ai-foundry'),
):
    if _source in FAMILY_CHECKS:
        FAMILY_CHECKS[_alias] = FAMILY_CHECKS[_source]

FAMILY_CHECKS['ec2'] |= frozenset({'INSTANCE_METADATA'})

# Azure Monitor keys used to satisfy UTILIZATION_WINDOW / FIVE_MINUTE_UTILIZATION.
FAMILY_UTILIZATION_METRICS: dict[str, tuple[str, ...]] = {
    'managed-disks': ('iops', 'throughput'),
    'virtual-machines': ('cpu_percent', 'disk_iops', 'disk_queue', 'burst_credits'),
    'ip-nat': ('ingress_bytes', 'network_bytes', 'connections'),
    'gateways': ('requests', 'healthy_targets', 'capacity_units', 'latency'),
    'app-service': ('cpu_percent', 'memory_percent', 'http_queue'),
    'sql-postgres': ('cpu_percent', 'memory_percent', 'connections', 'iops'),
    'cosmosdb': ('normalized_ru_consumption',),
    'redis': ('memory_percent', 'cpu_percent', 'connections', 'evictions'),
    'blob-storage': ('bytes', 'requests'),
    'ai-foundry': ('ptu_utilization', 'invocations'),
    'network-orphan': (),
    'aks': ('cpu_percent', 'memory_percent'),
    'containers': ('cpu_percent', 'memory_percent'),
    'messaging': ('requests', 'connections'),
    'platform': ('requests',),
    'integration': ('requests',),
    'analytics': ('requests',),
    'compute-other': ('cpu_percent', 'network_bytes'),
    'network-other': ('ingress_bytes', 'network_bytes'),
    'application-other': ('cpu_percent', 'memory_percent', 'requests'),
}

for _alias, _source in (
    ('ebs', 'managed-disks'),
    ('persistent-disks', 'managed-disks'),
    ('s3', 'blob-storage'),
    ('ec2', 'virtual-machines'),
    ('gce', 'virtual-machines'),
    ('eip-nat', 'ip-nat'),
    ('load-balancers', 'gateways'),
    ('rds-aurora', 'sql-postgres'),
    ('sql-alloydb', 'sql-postgres'),
    ('dynamodb', 'cosmosdb'),
    ('elasticache', 'redis'),
    ('bigquery', 'cosmosdb'),
    ('lambda-ecs', 'app-service'),
    ('cloudrun-memorystore', 'app-service'),
    ('ai-inference', 'ai-foundry'),
    ('vertex-ai', 'ai-foundry'),
):
    if _source in FAMILY_UTILIZATION_METRICS and _alias not in FAMILY_UTILIZATION_METRICS:
        FAMILY_UTILIZATION_METRICS[_alias] = FAMILY_UTILIZATION_METRICS[_source]

# Resource types with dedicated check profiles before catalog family().
TYPE_ALIASES: dict[str, str] = {}

TYPE_CHECKS: dict[str, FrozenSet[str]] = {}

TYPE_UTILIZATION_METRICS: dict[str, tuple[str, ...]] = {}

_KIND_FALLBACK: dict[str, FrozenSet[str]] = {
    'compute': BASELINE | _OPS_COMPUTE | frozenset({'ACCESS_AND_EXPOSURE', 'PUBLIC_EXPOSURE'}) | _UTIL_COMPUTE | _PERF_VM,
    'storage': BASELINE | _COST_DISK | _RELIABILITY_SNAP | _SECURITY_ENCRYPT | frozenset({'PUBLIC_EXPOSURE'}) | _UTIL_STANDARD,
    'database': BASELINE | _RELIABILITY_DB | _RELIABILITY_HA | _SECURITY_DB | _SECURITY_ENCRYPT | _UTIL_DATA | _PERF_DATA,
    'application': BASELINE | _COST_APP | _SECURITY_APP | frozenset({'PUBLIC_EXPOSURE'}) | _UTIL_COMPUTE,
    'network': BASELINE | _SECURITY_NET | frozenset({'PUBLIC_EXPOSURE', 'ACCESS_AND_EXPOSURE'}) | _UTIL_STANDARD,
    'ai': BASELINE | frozenset({'KEYLESS_LOCAL_AUTH', 'MODEL_GUARDRAIL', 'PUBLIC_EXPOSURE'}) | _UTIL_DATA,
    'other': BASELINE,
}


@dataclass(frozen=True)
class EvidenceProfile:
    family: str | None
    family_label: str
    resource_type: str
    checks: FrozenSet[str]
    utilization_metrics: tuple[str, ...]


def normalize_resource_type(finding: dict) -> str:
    return (finding.get('resource_type') or '').lower()


def _family_label(family_id: str | None, *, kind: str) -> str:
    if not family_id:
        return kind.replace('_', ' ').title() if kind else 'Resource'
    for provider, fid, category, types, _rules in FAMILIES:
        if fid == family_id:
            return fid.replace('-', ' ').title()
    return family_id.replace('-', ' ').title()


def evidence_profile(finding: dict) -> EvidenceProfile:
    from app.assessment import category as service_kind
    from app.azure_resource_registry import resolve_family_id, utilization_metrics_for

    rtype = normalize_resource_type(finding)
    kind = service_kind(finding)
    alias = TYPE_ALIASES.get(rtype)
    if alias:
        return EvidenceProfile(
            family=alias,
            family_label=_family_label(alias, kind=kind),
            resource_type=rtype,
            checks=TYPE_CHECKS.get(alias, _KIND_FALLBACK.get(kind, BASELINE)),
            utilization_metrics=TYPE_UTILIZATION_METRICS.get(alias, ()),
        )
    fam = family(finding)
    if fam:
        family_id = fam[1]
        metrics = FAMILY_UTILIZATION_METRICS.get(family_id, ())
        if finding.get('cloud_provider', 'azure') == 'azure':
            reg = utilization_metrics_for(finding)
            if reg:
                metrics = reg
        return EvidenceProfile(
            family=family_id,
            family_label=_family_label(family_id, kind=kind),
            resource_type=rtype,
            checks=FAMILY_CHECKS.get(family_id, _KIND_FALLBACK.get(fam[2], BASELINE)),
            utilization_metrics=metrics,
        )
    if finding.get('cloud_provider', 'azure') == 'azure':
        family_id = resolve_family_id(finding)
        if family_id:
            return EvidenceProfile(
                family=family_id,
                family_label=_family_label(family_id, kind=kind),
                resource_type=rtype,
                checks=FAMILY_CHECKS.get(family_id, _KIND_FALLBACK.get(kind, BASELINE)),
                utilization_metrics=utilization_metrics_for(finding),
            )
    return EvidenceProfile(
        family=None,
        family_label=_family_label(None, kind=kind),
        resource_type=rtype,
        checks=_KIND_FALLBACK.get(kind, BASELINE),
        utilization_metrics=(),
    )


def check_allowed(code: str, profile: EvidenceProfile | None) -> bool:
    if profile is None:
        return True
    return code in profile.checks


def exposure_field_keys(profile: EvidenceProfile, kind: str) -> tuple[str, ...]:
    if 'microsoft.storage/storageaccounts' in profile.resource_type:
        return ('public_snapshot', 'allow_blob_public_access')
    if profile.family == 'ip-nat' or 'publicipaddresses' in profile.resource_type:
        return ('association_verified', 'unrestricted_ingress')
    if profile.family in ('gateways',) or 'applicationgateway' in profile.resource_type:
        return ('unrestricted_ingress', 'ddos_or_waf_enabled')
    if profile.family in ('app-service',) or 'microsoft.web/' in profile.resource_type:
        return ('https_only',)
    if kind == 'compute':
        return ('public_admin_ingress', 'publicly_accessible')
    if kind == 'database':
        return ('publicly_accessible',)
    return ('publicly_accessible',)
