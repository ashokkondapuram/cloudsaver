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


def mock_client(responses):
    def handler(request):
        key = request.url.params.get('$filter', '')
        items = responses.get(key, [])
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
    assert priced['estimated_monthly_waste_usd'] == 15.71


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
