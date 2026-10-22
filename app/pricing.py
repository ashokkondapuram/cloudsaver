"""Retail list-price estimates require exact meter evidence; missing evidence stays unknown."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

ENDPOINT = 'https://prices.azure.com/api/retail/prices'


class ConfidenceLevel(str, Enum):
    HIGH = 'HIGH'
    UNKNOWN = 'UNKNOWN'


class WasteCostAttribution(BaseModel):
    monthly_waste_usd: float | None = None
    currency: str = 'USD'
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    calculation_basis: str = 'Exact retail meter evidence is unavailable'
    potential_waste_usd: float | None = None
    realizable_savings_usd: float | None = None
    unit_price: float | None = None
    unit_of_measure: str | None = None
    is_live_attributed: bool = False
    estimate_type: str = 'retail_list_price'
    meter_id: str | None = None
    retrieved_at: str | None = None


class AzurePricingClient:
    def __init__(self, *, transport=None, timeout=5):
        self.transport = transport
        self.timeout = timeout

    def fetch_price(self, evidence):
        required = ('region', 'sku_name', 'meter_name', 'product_name', 'meter_id')
        if any(not isinstance(evidence.get(k), str) or not evidence[k] or len(evidence[k]) > 256 for k in required):
            return None
        filters = {'armRegionName': evidence['region'], 'skuName': evidence['sku_name'],
                   'meterName': evidence['meter_name'], 'productName': evidence['product_name'],
                   'meterId': evidence['meter_id'], 'priceType': 'Consumption'}
        query = ' and '.join(k + " eq '" + v.replace("'", "''") + "'" for k, v in filters.items())
        params = {'$filter': query, 'currencyCode': 'USD'}
        matches, seen = [], set()
        url = ENDPOINT
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport, follow_redirects=False) as client:
                for _ in range(20):
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data.get('Items'), list):
                        return None
                    for item in data['Items']:
                        if (all(item.get(k) == v for k, v in filters.items() if k != 'priceType')
                                and item.get('type') == 'Consumption' and item.get('currencyCode') == 'USD'
                                and item.get('unitOfMeasure') == '1 Hour' and item.get('tierMinimumUnits') == 0
                                and item.get('isPrimaryMeterRegion') is True):
                            start = datetime.fromisoformat(item['effectiveStartDate'].replace('Z', '+00:00'))
                            if start <= datetime.now(timezone.utc):
                                matches.append(item)
                    next_page = data.get('NextPageLink')
                    if not next_page:
                        # Ambiguous meters or historical rates are not silently selected.
                        return matches[0] if len(matches) == 1 else None
                    parsed = urlparse(next_page)
                    if (parsed.scheme != 'https' or parsed.hostname != 'prices.azure.com'
                            or parsed.path != '/api/retail/prices' or parsed.username or parsed.password
                            or parsed.port not in (None, 443) or parsed.fragment or next_page in seen):
                        return None
                    seen.add(next_page)
                    url, params = next_page, None
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return None
        return None

    def attribute(self, finding):
        unknown = WasteCostAttribution()
        # Disk tiers and stopped-VM storage require separate meter/usage models.
        if finding.get('rule_id') not in ('UNASSOCIATED_PUBLIC_IP', 'EMPTY_APP_SERVICE_PLAN'):
            return unknown
        evidence = finding.get('pricing_evidence')
        if not isinstance(evidence, dict):
            return unknown
        quantity = evidence.get('quantity')
        if type(quantity) is not int or not 1 <= quantity <= 100000:
            return unknown
        item = self.fetch_price(evidence)
        if not item:
            return unknown
        try:
            price = Decimal(str(item['unitPrice']))
            if not price.is_finite() or price < 0:
                return unknown
            monthly = float((price * Decimal('730') * quantity).quantize(Decimal('0.01')))
        except (InvalidOperation, TypeError, KeyError, ValueError, OverflowError):
            return unknown
        return WasteCostAttribution(monthly_waste_usd=monthly, potential_waste_usd=monthly,
            confidence=ConfidenceLevel.HIGH, unit_price=float(price), unit_of_measure='1 Hour',
            is_live_attributed=True, meter_id=evidence['meter_id'], retrieved_at=datetime.now(timezone.utc).isoformat(),
            calculation_basis='Exact USD retail consumption meter and explicit resource quantity; illustrative 730-hour month. Excludes contract discounts, taxes, commitments and remediation costs. Not verified savings.')


pricing_client = AzurePricingClient()


def attribute_finding_cost(finding, region=None):
    attribution = pricing_client.attribute(finding)
    return dict(finding, estimated_monthly_waste_usd=attribution.monthly_waste_usd,
                cost_attribution=attribution.model_dump(mode='json'))
