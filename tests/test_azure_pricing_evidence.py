import httpx

from app.azure_pricing_evidence import build_pricing_evidence, enrich_azure_pricing_evidence, inventory_retail_usd
from app.pricing import AzurePricingClient, attribute_finding_cost

DISK_ITEM = dict(
    armRegionName='eastus', skuName='P10 LRS', meterName='P10 LRS Disk', productName='Premium SSD Managed Disks',
    meterId='disk-current', type='Consumption', currencyCode='USD', unitOfMeasure='1/Month',
    tierMinimumUnits=0, isPrimaryMeterRegion=True, effectiveStartDate='2026-01-01T00:00:00Z', unitPrice=19.71,
)
SNAP_ITEM = dict(
    armRegionName='eastus', skuName='Snapshots LRS', meterName='LRS Snapshots', productName='Storage',
    meterId='snap-meter', type='Consumption', currencyCode='USD', unitOfMeasure='1 GB/Month',
    tierMinimumUnits=0, isPrimaryMeterRegion=True, effectiveStartDate='2026-01-01T00:00:00Z', unitPrice=0.05,
)
IP_ITEM = dict(
    armRegionName='eastus', skuName='Standard', meterName='Static IP', productName='Public IP',
    meterId='ip-meter', type='Consumption', currencyCode='USD', unitOfMeasure='1 Hour',
    tierMinimumUnits=0, isPrimaryMeterRegion=True, effectiveStartDate='2026-01-01T00:00:00Z', unitPrice=0.005,
)


def _filter_matches(key: str, pattern: str) -> bool:
    return all(part in key for part in pattern.split(' and ') if part.strip())


def mock_client(responses):
    def handler(request):
        key = request.url.params.get('$filter', '')
        items = responses.get(key)
        if items is None:
            for pattern, rows in responses.items():
                if _filter_matches(key, pattern):
                    items = rows
                    break
        items = items or []
        return httpx.Response(200, json={'Items': items, 'NextPageLink': None})

    return AzurePricingClient(transport=httpx.MockTransport(handler))


def test_disk_finding_builds_composite_pricing_evidence():
    filters = {
        "armRegionName eq 'eastus' and productName eq 'Premium SSD Managed Disks' and skuName eq 'P10 LRS' and meterName eq 'P10 LRS Disk' and priceType eq 'Consumption'": [DISK_ITEM],
        "armRegionName eq 'eastus' and productName eq 'Storage' and skuName eq 'Snapshots LRS' and meterName eq 'LRS Snapshots' and priceType eq 'Consumption'": [SNAP_ITEM],
    }
    client = mock_client(filters)
    finding = dict(
        cloud_provider='azure',
        rule_id='AZURE_DISK_UNATTACHED_RETENTION',
        resource_type='microsoft.compute/disks',
        region='eastus',
        evidence=dict(size_gb=128, sku_name='Premium_LRS'),
    )
    evidence = build_pricing_evidence(finding, client=client)
    assert evidence and 'components' in evidence
    priced = attribute_finding_cost(dict(finding, pricing_evidence=evidence), client=client)
    assert priced['estimated_monthly_waste_usd'] == 13.31


def test_public_ip_legacy_pricing_evidence():
    key = "armRegionName eq 'eastus' and productName eq 'Public IP' and skuName eq 'Standard' and meterName eq 'Static IP' and priceType eq 'Consumption'"
    client = mock_client({key: [IP_ITEM]})
    finding = dict(
        cloud_provider='azure',
        rule_id='AZURE_PUBLIC_IP_UNASSOCIATED',
        region='eastus',
        evidence=dict(sku_name='Standard'),
    )
    enriched = enrich_azure_pricing_evidence(finding, client=client)
    priced = attribute_finding_cost(enriched, client=client)
    assert priced['estimated_monthly_waste_usd'] == 3.65


def test_inventory_retail_uses_current_component_only():
    key = "armRegionName eq 'eastus' and productName eq 'Premium SSD Managed Disks' and skuName eq 'P10 LRS' and meterName eq 'P10 LRS Disk' and priceType eq 'Consumption'"
    client = mock_client({key: [DISK_ITEM]})
    observation = dict(
        cloud_provider='azure',
        resource_type='microsoft.compute/disks',
        region='eastus',
        evidence=dict(size_gb=128, sku_name='Premium_LRS'),
    )
    assert inventory_retail_usd(observation, client=client) == 19.71


def test_standard_ssd_uses_e_tiers_not_premium():
    item = dict(
        DISK_ITEM,
        skuName='E10 LRS',
        meterName='E10 LRS Disk',
        productName='Standard SSD Managed Disks',
        unitPrice=5.0,
    )
    key = "armRegionName eq 'eastus' and productName eq 'Standard SSD Managed Disks' and skuName eq 'E10 LRS' and meterName eq 'E10 LRS Disk' and priceType eq 'Consumption'"
    client = mock_client({key: [item]})
    finding = dict(
        cloud_provider='azure',
        rule_id='AZURE_INVENTORY_RETAIL',
        resource_type='microsoft.compute/disks',
        region='eastus',
        evidence=dict(size_gb=128, sku_name='StandardSSD_LRS'),
    )
    assert inventory_retail_usd(dict(finding, evidence=finding['evidence']), client=client) == 5.0


def test_standard_hdd_uses_size_tier_not_flat_s4_gb():
    item = dict(
        DISK_ITEM,
        skuName='S10 LRS',
        meterName='S10 LRS Disk',
        productName='Standard HDD Managed Disks',
        unitPrice=4.8,
    )
    key = "armRegionName eq 'eastus' and productName eq 'Standard HDD Managed Disks' and skuName eq 'S10 LRS' and meterName eq 'S10 LRS Disk' and priceType eq 'Consumption'"
    client = mock_client({key: [item]})
    observation = dict(
        cloud_provider='azure',
        resource_type='microsoft.compute/disks',
        region='eastus',
        evidence=dict(size_gb=128, sku_name='Standard_LRS'),
    )
    assert inventory_retail_usd(observation, client=client) == 4.8


def test_resource_retail_run_rate_differs_from_waste_delta():
    disk_filters = {
        "armRegionName eq 'eastus' and productName eq 'Premium SSD Managed Disks' and skuName eq 'P10 LRS' and meterName eq 'P10 LRS Disk' and priceType eq 'Consumption'": [DISK_ITEM],
        "armRegionName eq 'eastus' and productName eq 'Storage' and skuName eq 'Snapshots LRS' and meterName eq 'LRS Snapshots' and priceType eq 'Consumption'": [SNAP_ITEM],
    }
    client = mock_client(disk_filters)
    finding = dict(
        cloud_provider='azure',
        rule_id='AZURE_DISK_UNATTACHED_RETENTION',
        resource_type='microsoft.compute/disks',
        resource_id='/subscriptions/x/resourceGroups/r/providers/Microsoft.Compute/disks/d',
        region='eastus',
        evidence=dict(size_gb=128, sku_name='Premium_LRS'),
    )
    enriched = enrich_azure_pricing_evidence(finding, client=client)
    priced = attribute_finding_cost(enriched, client=client)
    assert priced['estimated_monthly_waste_usd'] == 13.31
    from app.azure_pricing_evidence import resource_retail_run_rate_usd

    assert resource_retail_run_rate_usd([priced], client=client) == 19.71
