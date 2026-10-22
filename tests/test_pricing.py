from copy import deepcopy

import httpx
import pytest

from app.pricing import AzurePricingClient, attribute_finding_cost

EVIDENCE = dict(region='eastus', sku_name='Standard', meter_name='Static IP', product_name='Public IP', meter_id='meter-1', quantity=1)
ITEM = dict(armRegionName='eastus', skuName='Standard', meterName='Static IP', productName='Public IP',
            meterId='meter-1', type='Consumption', currencyCode='USD', unitOfMeasure='1 Hour',
            tierMinimumUnits=0, isPrimaryMeterRegion=True, effectiveStartDate='2026-01-01T00:00:00Z', unitPrice=0.005)


def client(items, next_page=None):
    def handler(request):
        assert '$filter' in request.url.params
        assert request.url.params['currencyCode'] == 'USD'
        return httpx.Response(200, json={'Items': items, 'NextPageLink': next_page})
    return AzurePricingClient(transport=httpx.MockTransport(handler))


def test_exact_meter_estimate_has_evidence_and_no_invented_net_savings():
    result = client([ITEM]).attribute(dict(rule_id='UNASSOCIATED_PUBLIC_IP', pricing_evidence=EVIDENCE))
    assert result.monthly_waste_usd == 3.65
    assert result.realizable_savings_usd is None
    assert result.is_live_attributed and result.meter_id == 'meter-1' and result.retrieved_at
    assert result.estimate_type == 'retail_list_price'


@pytest.mark.parametrize('rule', ['ORPHANED_DISK', 'STOPPED_VM', 'UNKNOWN_RULE', 'EMPTY_APP_SERVICE_PLAN'])
def test_missing_or_unsupported_evidence_stays_unknown(rule):
    result = attribute_finding_cost({'rule_id': rule, 'estimated_monthly_waste_usd': 999})
    assert result['estimated_monthly_waste_usd'] is None
    assert result['cost_attribution']['realizable_savings_usd'] is None
    assert result['cost_attribution']['is_live_attributed'] is False


@pytest.mark.parametrize('change', [{'armRegionName':'westus'}, {'currencyCode':'EUR'}, {'unitOfMeasure':'1 GB/Month'},
                                    {'unitPrice':-1}, {'type':'Reservation'}, {'isPrimaryMeterRegion':False},
                                    {'unitPrice':'NaN'}, {'effectiveStartDate':'2099-01-01T00:00:00Z'}])
def test_inconsistent_meter_or_price_is_unknown(change):
    item = dict(ITEM, **change)
    assert client([item]).attribute(dict(rule_id='UNASSOCIATED_PUBLIC_IP', pricing_evidence=EVIDENCE)).monthly_waste_usd is None


def test_ambiguous_results_and_untrusted_pagination_are_unknown():
    for api in (client([ITEM, ITEM]), client([ITEM], 'https://evil.example/collect')):
        assert api.attribute(dict(rule_id='UNASSOCIATED_PUBLIC_IP', pricing_evidence=EVIDENCE)).monthly_waste_usd is None


def test_provider_failure_never_falls_back_to_benchmarks():
    api = AzurePricingClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert api.attribute(dict(rule_id='UNASSOCIATED_PUBLIC_IP', pricing_evidence=EVIDENCE)).monthly_waste_usd is None


def test_resource_quantity_is_required_and_applied():
    finding = dict(rule_id='EMPTY_APP_SERVICE_PLAN', pricing_evidence=dict(EVIDENCE,quantity=3))
    assert client([ITEM]).attribute(finding).monthly_waste_usd == 10.95
    finding['pricing_evidence'].pop('quantity')
    assert client([ITEM]).attribute(finding).monthly_waste_usd is None
