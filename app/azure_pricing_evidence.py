"""Build exact Azure retail meter selectors for findings and inventory rows."""
from __future__ import annotations

from app.rule_id_canonical import canonical_rule_id

_PREMIUM_GB_TIERS = (
    (4, 'P1'),
    (8, 'P2'),
    (16, 'P3'),
    (32, 'P4'),
    (64, 'P6'),
    (128, 'P10'),
    (256, 'P15'),
    (512, 'P20'),
    (1024, 'P30'),
    (2048, 'P40'),
    (4096, 'P50'),
    (8192, 'P60'),
    (16384, 'P70'),
    (32767, 'P80'),
)

_STANDARD_SSD_GB_TIERS = (
    (4, 'E1'),
    (8, 'E2'),
    (16, 'E3'),
    (32, 'E4'),
    (64, 'E6'),
    (128, 'E10'),
    (256, 'E15'),
    (512, 'E20'),
    (1024, 'E30'),
    (2048, 'E40'),
    (4096, 'E50'),
    (8192, 'E60'),
    (16384, 'E70'),
    (32767, 'E80'),
)

_STANDARD_HDD_GB_TIERS = (
    (32, 'S4'),
    (64, 'S6'),
    (128, 'S10'),
    (256, 'S15'),
    (512, 'S20'),
    (1024, 'S30'),
    (2048, 'S40'),
    (4096, 'S50'),
    (8192, 'S60'),
    (16384, 'S70'),
    (32767, 'S80'),
)


def _normalize_region(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    region = value.strip()
    if not region:
        return None
    if ' ' in region:
        region = region.replace(' ', '').lower()
    return region


def _region(finding: dict, observation: dict | None) -> str | None:
    for source in (finding, observation or {}):
        region = _normalize_region(source.get('region'))
        if region:
            return region
    return None


def _evidence(finding: dict, observation: dict | None) -> dict:
    merged = dict((observation or {}).get('evidence') or {})
    merged.update(finding.get('evidence') or {})
    return merged


def _tier_retail_sku(size_gb: int, tiers: tuple[tuple[int, str], ...], *, fallback: str) -> str | None:
    if type(size_gb) is not int or size_gb <= 0 or size_gb > 32767:
        return None
    for limit, tier in tiers:
        if size_gb <= limit:
            return f'{tier} LRS'
    return fallback


def _premium_retail_sku(size_gb: int) -> str | None:
    return _tier_retail_sku(size_gb, _PREMIUM_GB_TIERS, fallback='P80 LRS')


def _standard_ssd_retail_sku(size_gb: int) -> str | None:
    return _tier_retail_sku(size_gb, _STANDARD_SSD_GB_TIERS, fallback='E80 LRS')


def _standard_hdd_retail_sku(size_gb: int) -> str | None:
    return _tier_retail_sku(size_gb, _STANDARD_HDD_GB_TIERS, fallback='S80 LRS')


def _disk_components(client, *, region: str, arm_sku: str, size_gb: int, include_snapshot: bool):
    from app.pricing import pricing_client

    api = client or pricing_client
    arm = (arm_sku or '').strip()
    if not arm:
        return None
    arm_lower = arm.casefold()
    if arm_lower in ('premium_lrs', 'premium_zrs'):
        retail_sku = _premium_retail_sku(size_gb)
        if not retail_sku:
            return None
        product = 'Premium SSD Managed Disks'
        meter = f'{retail_sku} Disk'
        unit = '1/Month'
        quantity = 1
    elif arm_lower in ('standardssd_lrs', 'standardssd_zrs'):
        retail_sku = _standard_ssd_retail_sku(size_gb)
        if not retail_sku:
            return None
        product = 'Standard SSD Managed Disks'
        meter = f'{retail_sku} Disk'
        unit = '1/Month'
        quantity = 1
    elif arm_lower in ('standard_lrs', 'standard_zrs'):
        retail_sku = _standard_hdd_retail_sku(size_gb)
        if not retail_sku:
            return None
        product = 'Standard HDD Managed Disks'
        meter = f'{retail_sku} Disk'
        unit = '1/Month'
        quantity = 1
    elif arm_lower in ('premiumv2_lrs',):
        product = 'Premium SSD v2 Managed Disks'
        retail_sku = 'Premium LRS Provisioned'
        meter = 'Premium LRS Provisioned Capacity'
        unit = '1 GB/Month'
        quantity = size_gb
    else:
        return None
    current = api.discover_meter(
        region=region,
        product_name=product,
        sku_name=retail_sku,
        meter_name=meter,
        unit_of_measure=unit,
    )
    if not current:
        return None
    rows = {'current': [{**current, 'quantity': quantity, 'unit_of_measure': unit}]}
    if include_snapshot:
        snap_product = 'Storage'
        snap_sku = 'Snapshots LRS'
        snap_meter = 'LRS Snapshots'
        snapshot = api.discover_meter(
            region=region,
            product_name=snap_product,
            sku_name=snap_sku,
            meter_name=snap_meter,
            unit_of_measure='1 GB/Month',
        )
        if not snapshot:
            return None
        rows['snapshot'] = [{**snapshot, 'quantity': size_gb, 'unit_of_measure': '1 GB/Month'}]
    return dict(components=rows)


def _public_ip_component(client, *, region: str, sku_name: str | None):
    from app.pricing import pricing_client

    api = client or pricing_client
    sku = (sku_name or 'Standard').strip() or 'Standard'
    row = api.discover_meter(
        region=region,
        product_name='Public IP',
        sku_name=sku,
        meter_name='Static IP',
        unit_of_measure='1 Hour',
    )
    if not row:
        row = api.discover_meter(
            region=region,
            product_name='IP Addresses',
            sku_name='Standard IPv4',
            meter_name='Standard IPv4 Static Public IP',
            unit_of_measure='1 Hour',
        )
    return row


def _asp_component(client, *, region: str, sku_name: str | None):
    from app.pricing import pricing_client

    api = client or pricing_client
    sku = (sku_name or 'S1').strip() or 'S1'
    row = api.discover_meter(
        region=region,
        product_name='Azure App Service',
        sku_name=sku,
        meter_name=sku,
        unit_of_measure='1 Hour',
    )
    return row


def build_pricing_evidence(finding: dict, observation: dict | None = None, *, client=None):
    """Return pricing_evidence dict or None when meters cannot be resolved unambiguously."""
    if finding.get('cloud_provider', 'azure') != 'azure':
        return None
    region = _region(finding, observation)
    if not region:
        return None
    evidence = _evidence(finding, observation)
    rule_id = canonical_rule_id(finding.get('rule_id') or '')
    kind = (finding.get('resource_type') or '').casefold()

    if rule_id == 'AZURE_DISK_UNATTACHED_RETENTION' or (
        rule_id == 'AZURE_INVENTORY_RETAIL' and 'microsoft.compute/disks' in kind
    ):
        size_gb = evidence.get('size_gb')
        if type(size_gb) is not int:
            return None
        arm_sku = evidence.get('sku_name') or evidence.get('sku')
        include_snapshot = rule_id == 'AZURE_DISK_UNATTACHED_RETENTION'
        return _disk_components(client, region=region, arm_sku=str(arm_sku or ''), size_gb=size_gb, include_snapshot=include_snapshot)

    if rule_id in ('AZURE_PUBLIC_IP_UNASSOCIATED',) or (
        rule_id == 'AZURE_INVENTORY_RETAIL' and 'microsoft.network/publicipaddresses' in kind
    ):
        row = _public_ip_component(client, region=region, sku_name=evidence.get('sku_name'))
        if not row:
            return None
        return dict(row, quantity=1)

    if rule_id in ('AZURE_ASP_EMPTY_PAID_PLAN',) or (
        rule_id == 'AZURE_INVENTORY_RETAIL' and 'microsoft.web/serverfarms' in kind
    ):
        row = _asp_component(client, region=region, sku_name=evidence.get('sku_name'))
        if not row:
            return None
        return dict(row, quantity=1)

    return None


def enrich_azure_pricing_evidence(finding: dict, observation: dict | None = None, *, client=None) -> dict:
    if finding.get('pricing_evidence'):
        return finding
    merged = dict(finding)
    if observation:
        if not merged.get('region') and observation.get('region'):
            merged['region'] = observation['region']
        merged['evidence'] = dict(observation.get('evidence') or {}, **(merged.get('evidence') or {}))
    built = build_pricing_evidence(merged, observation, client=client)
    if not built:
        return merged if merged is not finding else finding
    return dict(merged, pricing_evidence=built)


def resource_retail_run_rate_usd(findings: list[dict], *, client=None) -> float | None:
    """Monthly retail run-rate for a resource (current meters), not waste deltas."""
    if not findings:
        return None
    first = findings[0]
    evidence: dict = {}
    region = None
    for row in findings:
        if row.get('region'):
            region = row['region']
        evidence.update(row.get('evidence') or {})
    observation = dict(
        cloud_provider=first.get('cloud_provider', 'azure'),
        resource_type=first.get('resource_type', ''),
        region=region or first.get('region'),
        evidence=evidence,
    )
    return inventory_retail_usd(observation, client=client)


def inventory_retail_usd(observation: dict, *, client=None) -> float | None:
    """Monthly retail run-rate for an inventory row without a finding (current meters only)."""
    finding = dict(
        cloud_provider='azure',
        rule_id='AZURE_INVENTORY_RETAIL',
        resource_type=observation.get('resource_type', ''),
        region=observation.get('region'),
        evidence=observation.get('evidence') or {},
    )
    built = build_pricing_evidence(finding, observation, client=client)
    if not built:
        return None
    from app.pricing import attribute_finding_cost

    attributed = attribute_finding_cost(dict(finding, pricing_evidence=built), client=client)
    value = attributed.get('estimated_monthly_waste_usd')
    return float(value) if isinstance(value, (int, float)) else None


def index_inventory(inventory: list[dict]) -> dict[str, dict]:
    indexed = {}
    for row in inventory or []:
        if not isinstance(row, dict):
            continue
        resource_id = row.get('resource_id')
        if isinstance(resource_id, str) and resource_id:
            indexed[resource_id.casefold()] = row
    return indexed
