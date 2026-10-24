"""Retail list-price estimates require exact meter evidence; missing evidence stays unknown."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

ENDPOINT = 'https://prices.azure.com/api/retail/prices'


def opportunity_totals(findings, *, realized=False):
    """Conservative overlap rollup. Unknown alternatives keep the total unknown.

    Collectors can supply a verified shared workload group. Otherwise findings on one resource
    are competing alternatives. Never infer parent topology from names or tags.
    """
    groups = {}
    for finding in findings:
        provider = finding.get('cloud_provider', 'azure')
        resource_id = finding.get('resource_id')
        if not isinstance(resource_id, str) or not resource_id:
            groups.setdefault('unattributed', []).append(None)
            continue
        identity = resource_id.lower() if provider == 'azure' else resource_id
        key = finding.get('opportunity_group_id') or f'{provider}:{identity}'
        amount = ((finding.get('cost_attribution') or {}).get('realizable_savings_usd') if realized
                  else finding.get('estimated_monthly_waste_usd'))
        if type(amount) not in (int, float, Decimal):
            parsed = None
        else:
            parsed = Decimal(str(amount))
            if not parsed.is_finite() or parsed < 0:
                parsed = None
        groups.setdefault(key, []).append(parsed)
    known = Decimal(0)
    incomplete = 0
    for amounts in groups.values():
        observed = [value for value in amounts if value is not None]
        if observed:
            known += max(observed)
        incomplete += any(value is None for value in amounts)
    return dict(total_monthly_opportunity_usd=float(known.quantize(Decimal('.01'))) if groups and not incomplete else None,
                known_monthly_opportunity_usd=float(known.quantize(Decimal('.01'))) if groups else None,
                opportunity_group_count=len(groups), unpriced_group_count=incomplete,
                overlap_basis='maximum observed alternative per verified group or resource; compatibility not inferred')


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
                                and item.get('unitOfMeasure') == evidence.get('unit_of_measure','1 Hour') and item.get('tierMinimumUnits') == 0
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

    def component(self, evidence):
        if not isinstance(evidence,dict):return None
        quantity=evidence.get('quantity');unit=evidence.get('unit_of_measure','1 Hour')
        if type(quantity) not in (int,float,str) or isinstance(quantity,bool):return None
        try:
            quantity=Decimal(str(quantity))
            if not quantity.is_finite() or not 0<=quantity<=Decimal('1e9'):return None
        except InvalidOperation:return None
        if unit not in ('1 Hour','1/Month','1 Month','1 GB/Month','1 GiB/Month','1 GiB Hour'):return None
        item=self.fetch_price(evidence)
        if not item:return None
        try:
            price=Decimal(str(item['unitPrice']))
            if not price.is_finite() or price<0:return None
            amount=price*quantity*(730 if unit in ('1 Hour','1 GiB Hour') else 1)
            return amount,item
        except (InvalidOperation,KeyError,TypeError,ValueError):return None

    def attribute(self, finding):
        unknown=WasteCostAttribution()
        if finding.get('cloud_provider','azure')!='azure':return regional_attribution(finding)
        evidence=finding.get('pricing_evidence')
        if not isinstance(evidence,dict):return unknown
        rid=finding.get('rule_id','');observed=finding.get('evidence') or {}
        legacy=rid in ('UNASSOCIATED_PUBLIC_IP','EMPTY_APP_SERVICE_PLAN','AZURE_PUBLIC_IP_UNASSOCIATED','AZURE_ASP_EMPTY_PAID_PLAN')
        if legacy:
            quantity=evidence.get('quantity')
            if type(quantity) is not int or not 1<=quantity<=100000:return unknown
            value=self.component(evidence)
            if value is None:return unknown
            amount,item=value
        else:
            components=evidence.get('components')
            if not isinstance(components,dict) or not components or len(components)>24:return unknown
            allowed={'current','snapshot','target','compute','disks','gateway_fixed','gateway_capacity'}
            if set(components)-allowed:return unknown
            values={}
            for key,rows in components.items():
                rows=rows if isinstance(rows,list) else [rows]
                if not 1<=len(rows)<=16:return unknown
                parsed=[self.component(row) for row in rows]
                if any(value is None for value in parsed):return unknown
                values[key]=sum(value[0] for value in parsed)
            required=set();amount=None
            if rid in ('ORPHANED_DISK','AZURE_DISK_UNATTACHED_RETENTION'):
                required={'current','snapshot'}
                if required<=values.keys():amount=values['current']-values['snapshot']
            elif rid in ('AZURE_DISK_PROVISIONED_PERFORMANCE','AZURE_VM_RIGHTSIZING_UTILIZATION'):
                required={'current','target'}
                if observed.get('target_compatibility_verified') is not True:return unknown
                if required<=values.keys():amount=values['current']-values['target']
            elif rid in ('STOPPED_VM','AZURE_VM_STOPPED_RESIDUAL_COST'):
                state=observed.get('power_state');required={'disks'}
                if state=='PowerState/stopped':required.add('compute')
                elif state!='PowerState/deallocated':return unknown
                if required<=values.keys():amount=values['disks']+(values.get('compute',Decimal(0)) if state=='PowerState/stopped' else 0)
            elif rid=='IDLE_APP_GATEWAY':
                required={'gateway_fixed','gateway_capacity'}
                if required<=values.keys():amount=sum(values.values())
            if amount is None or amount<0 or set(values)!=required:return unknown
            item={'unitPrice':0,'unitOfMeasure':'composite regional retail meters','meterId':None}
        if amount>Decimal('1e12'):return unknown
        monthly=float(amount.quantize(Decimal('.01')))
        return WasteCostAttribution(monthly_waste_usd=monthly,potential_waste_usd=monthly,confidence=ConfidenceLevel.HIGH,
            unit_price=float(item['unitPrice']),unit_of_measure=item['unitOfMeasure'],is_live_attributed=True,meter_id=item.get('meterId'),
            retrieved_at=datetime.now(timezone.utc).isoformat(),calculation_basis='Exact regional USD consumption meters with explicit quantities, target compatibility and applicable snapshot overhead. 730-hour retail model; excludes taxes and contract discounts. Not verified savings.')


def regional_components(finding):
    """Concrete quantities from provider observations; catalog meters remain separately reviewed."""
    e=finding.get('evidence') or {};provider=finding.get('cloud_provider');rid=finding.get('rule_id','')
    def row(product,unit,quantity,role='current'):return dict(product=product,unit=unit,quantity=quantity,role=role)
    if rid in ('AWS_UNASSOCIATED_EIP','GCP_UNASSIGNED_ADDRESS'):
        return [row('public-ip:unassociated','hour',1)]
    if provider=='aws' and rid=='AWS_UNATTACHED_EBS':
        kind=e.get('volume_type');size=e.get('size_gb');iops=e.get('provisioned_iops');throughput=e.get('throughput_mibps')
        if kind not in ('gp2','gp3','io1','io2','st1','sc1') or type(size) is not int or size<=0:return None
        result=[row('ebs:'+kind+':storage','GB-month',size),row('ebs:snapshot','GB-month',size,'snapshot')]
        if kind=='io2' and type(iops) is int and iops>32000:return None
        if kind in ('gp3','io1','io2'):
            if type(iops) is not int or iops<0:return None
            extra=max(0,iops-3000) if kind=='gp3' else iops
            if extra:result.append(row('ebs:'+kind+':iops','IOPS-month',extra))
        if kind=='gp3':
            if type(throughput) is not int or throughput<0:return None
            if throughput>125:result.append(row('ebs:gp3:throughput','MiBps-month',throughput-125))
        return result
    if provider=='aws' and rid=='AWS_IDLE_RDS':
        size=e.get('allocated_storage_gb');kind=e.get('storage_type');iops=e.get('provisioned_iops')
        if type(size) is not int or size<=0 or kind not in ('gp2','gp3','io1','io2') or e.get('power_state')!='stopped':return None
        result=[row('rds:'+kind+':storage','GB-month',size)]
        if kind in ('io1','io2'):
            if type(iops) is not int or iops<0:return None
            result.append(row('rds:'+kind+':iops','IOPS-month',iops))
        return result
    if provider=='gcp' and rid=='GCP_UNATTACHED_DISK':
        kind=e.get('disk_type');size=e.get('size_gb')
        if kind not in ('pd-standard','pd-balanced','pd-ssd','pd-extreme','hyperdisk-balanced') or type(size) is not int or size<=0:return None
        result=[row('disk:'+kind+':storage','GiB-month',size),row('disk:snapshot','GiB-month',size,'snapshot')]
        if kind in ('pd-extreme','hyperdisk-balanced'):
            iops=e.get('billable_iops') if kind=='hyperdisk-balanced' else e.get('provisioned_iops')
            if type(iops) is not int or iops<0:return None
            result.append(row('disk:'+kind+':iops','IOPS-month',iops))
        if kind=='hyperdisk-balanced':
            throughput=e.get('billable_throughput')
            if type(throughput) is not int or throughput<0:return None
            result.append(row('disk:'+kind+':throughput','MiBps-month',throughput))
        return result
    if provider=='gcp' and rid=='GCP_IDLE_CLOUD_SQL':
        cpu=e.get('vcpu_count');memory=e.get('memory_gb');size=e.get('allocated_storage_gb');disk=e.get('storage_type');ha=e.get('availability_type')
        if type(cpu) is not int or cpu<=0 or type(memory) not in (int,float) or memory<=0 or type(size) is not int or size<=0 or disk not in ('PD_SSD','PD_HDD') or ha not in ('ZONAL','REGIONAL'):return None
        suffix=':'+ha.lower()
        return [row('cloud-sql:vcpu'+suffix,'vCPU-hour',cpu),row('cloud-sql:memory'+suffix,'GiB-hour',memory),row('cloud-sql:'+disk.lower()+':storage'+suffix,'GiB-month',size)]
    return None


def regional_attribution(finding):
    """Operator-reviewed regional meters, never universal hardcoded cloud prices.

    The catalog uses exact provider/region/product/unit identities and an expiring review.
    It supports provisioned GB, IOPS, throughput, vCPU, RAM and address-hour components.
    """
    import json,os
    unknown=WasteCostAttribution();raw=os.getenv('CLOUDSAVER_REGIONAL_PRICE_CATALOG','[]')
    if len(raw)>200000:return unknown
    try:
        catalog=json.loads(raw)
        if not isinstance(catalog,list) or len(catalog)>1000:return unknown
        e=finding.get('pricing_evidence') or {};components=e.get('regional_components') or regional_components(finding)
        if not isinstance(components,list) or not 1<=len(components)<=24:return unknown
        provider=finding['cloud_provider'];region=finding.get('region');total=Decimal(0);now=datetime.now(timezone.utc)
        for component in components:
            if set(component)!={'product','unit','quantity','role'} or component['role'] not in ('current','snapshot','target'):return unknown
            matches=[v for v in catalog if isinstance(v,dict) and (v.get('provider'),v.get('region'),v.get('product'),v.get('unit'),v.get('currency'))==(provider,region,component['product'],component['unit'],'USD')]
            if len(matches)!=1:return unknown
            meter=matches[0]
            reviewed=datetime.fromisoformat(meter['reviewed_at'].replace('Z','+00:00'));expires=datetime.fromisoformat(meter['expires_at'].replace('Z','+00:00'))
            source=urlparse(meter['source']);host=source.hostname
            if source.scheme!='https':return unknown
            if not reviewed.tzinfo or not expires.tzinfo or not reviewed<=now<expires or (expires-reviewed).days>90 or host not in ('aws.amazon.com','pricing.us-east-1.amazonaws.com','cloud.google.com','cloudbilling.googleapis.com'):return unknown
            rate=Decimal(meter['rate_usd']);quantity=Decimal(str(component['quantity']))
            if isinstance(component['quantity'],bool) or not rate.is_finite() or not quantity.is_finite() or rate<0 or quantity<0 or quantity>Decimal('1e9'):return unknown
            factor=730 if component['unit'] in ('hour','vCPU-hour','GiB-hour') else 1 if component['unit'] in ('GB-month','GiB-month','IOPS-month','MiBps-month','month') else None
            if factor is None:return unknown
            total+=rate*quantity*factor*(-1 if component['role'] in ('snapshot','target') else 1)
        rid=finding['rule_id']
        if any(x in rid for x in ('UNATTACHED','DISK_UNATTACHED')) and not any(c['role']=='snapshot' for c in components):return unknown
        if any(c['role']=='target' for c in components) and (finding.get('evidence') or {}).get('target_compatibility_verified') is not True:return unknown
        if not 0<=total<=Decimal('1e12'):return unknown
        amount=float(total.quantize(Decimal('.01')))
        return WasteCostAttribution(monthly_waste_usd=amount,potential_waste_usd=amount,confidence=ConfidenceLevel.HIGH,
            unit_of_measure='reviewed regional composite',is_live_attributed=False,estimate_type='operator_reviewed_regional_retail',retrieved_at=now.isoformat(),
            calculation_basis='Exact provider/region USD meter catalog with a current operator review; storage, IOPS, throughput, compute and snapshot/target components are separate. Retail estimate, not verified savings.')
    except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError):return unknown


pricing_client = AzurePricingClient()


def attribute_finding_cost(finding, region=None):
    attribution = pricing_client.attribute(finding)
    return dict(finding, estimated_monthly_waste_usd=attribution.monthly_waste_usd,
                cost_attribution=attribution.model_dump(mode='json'))
