"""Read-only commitment inventory and utilization: reservations, savings plans and committed use discounts.

No function here purchases, exchanges, renews or cancels a commitment.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import httpx

MAX_COMMITMENTS = 2000
FIELDS = ('provider','scope_id','commitment_id','kind','name','sku','region','term','quantity','status','start','end',
          'utilization_percent','utilization_window_days','commitment_amount','commitment_grain','unused_amount','net_savings','currency')


def commitment(**values):
    item = {field: values.get(field) for field in FIELDS}
    for field in ('quantity','utilization_percent','commitment_amount','unused_amount','net_savings'):
        if item[field] is not None:
            value = Decimal(str(item[field]))
            if not value.is_finite() or abs(value) > Decimal('1e15'): raise ValueError('Invalid commitment amount')
            item[field] = str(value)
    return item


def _get(url, token, params=None):
    with httpx.Client(timeout=httpx.Timeout(25, connect=5), follow_redirects=False) as client:
        with client.stream('GET', url, headers={'Authorization':'Bearer '+token}, params=params) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > 4_000_000: raise ValueError('Commitment response exceeds the limit')
            return json.loads(raw, parse_float=Decimal)


def _pages(url, token, *, host, key='value', next_key='nextLink'):
    items, page = [], url
    for _ in range(20):
        body = _get(page, token)
        items.extend(body.get(key, []))
        if len(items) > MAX_COMMITMENTS: raise ValueError('Commitment limit exceeded')
        page = body.get(next_key)
        if not page: return items
        if not page.startswith(host): raise ValueError('Unexpected commitment pagination host')
    raise ValueError('Commitment pagination limit exceeded')


def _azure_utilization(properties):
    aggregates = (properties.get('utilization') or {}).get('aggregates') or []
    best = None
    for item in aggregates:
        if str(item.get('grainUnit','')).lower() == 'days' and item.get('value') is not None and str(item.get('valueUnit','percentage')).lower() == 'percentage':
            window = int(Decimal(str(item.get('grain'))))
            if best is None or window > best[0]: best = (window, item['value'])
    return best or (None, None)


def _applies_to(properties, subscription):
    subscription = subscription.lower()
    scopes = [str(s).lower() for s in properties.get('appliedScopes') or []]
    applied = properties.get('appliedScopeProperties') or {}
    return (str(properties.get('appliedScopeType','')).lower() == 'shared'
            or subscription in str(properties.get('billingScopeId','')).lower()
            or any(subscription in s for s in scopes)
            or subscription in str(applied.get('subscriptionId','')).lower())


def azure_commitments(binding, tenant, start, end):
    from app.cloud_identity import azure_credential
    credential = azure_credential(tenant)
    host = 'https://management.azure.com/'
    try:
        token = credential.get_token('https://management.azure.com/.default').token
        result, warnings = [], []
        reservations = _pages(host+'providers/Microsoft.Capacity/reservations?api-version=2022-11-01&$expand=renewProperties', token, host=host)
        for row in reservations:
            p = row.get('properties') or {}
            if not _applies_to(p, binding['scope_id']): continue
            window, percent = _azure_utilization(p)
            result.append(commitment(provider='azure', scope_id=binding['scope_id'], commitment_id=row.get('id'), kind='reservation',
                name=p.get('displayName') or row.get('name'), sku=(row.get('sku') or {}).get('name'), region=row.get('location'),
                term=p.get('term'), quantity=p.get('quantity'), status=p.get('displayProvisioningState') or p.get('provisioningState'),
                start=p.get('effectiveDateTime') or p.get('purchaseDate'), end=p.get('expiryDateTime') or p.get('expiryDate'),
                utilization_percent=percent, utilization_window_days=window, commitment_grain=None))
        try:
            plans = _pages(host+'providers/Microsoft.BillingBenefits/savingsPlans?api-version=2022-11-01', token, host=host)
        except httpx.HTTPStatusError:
            plans = []; warnings.append('Savings plans could not be read. Grant Savings plan Reader to include them.')
        for row in plans:
            p = row.get('properties') or {}
            if not _applies_to(p, binding['scope_id']): continue
            window, percent = _azure_utilization(p)
            amount = p.get('commitment') or {}
            result.append(commitment(provider='azure', scope_id=binding['scope_id'], commitment_id=row.get('id'), kind='savings_plan',
                name=p.get('displayName') or row.get('name'), sku=(row.get('sku') or {}).get('name'), region=None, term=p.get('term'),
                status=p.get('displayProvisioningState') or p.get('provisioningState'), start=p.get('effectiveDateTime'), end=p.get('expiryDateTime'),
                utilization_percent=percent, utilization_window_days=window, commitment_amount=amount.get('amount'),
                commitment_grain=amount.get('grain'), currency=amount.get('currencyCode')))
        warnings.append('Reservations and savings plans shared across subscriptions appear on every subscription they can apply to.')
        return result, None, warnings
    finally:
        credential.close()


def aws_commitments(binding, tenant, start, end, *, client=None):
    if client is None:
        from botocore.config import Config
        from app.cloud_identity import aws_session
        source = next(x for x in tenant.get('aws_accounts',[]) if x['account_id']==binding['scope_id'])
        client = aws_session(source, tenant=tenant).client('ce', region_name='us-east-1', config=Config(connect_timeout=5,read_timeout=25,retries={'total_max_attempts':1}))
    period = {'Start':start.isoformat(),'End':end.isoformat()}
    account = {'Dimensions':{'Key':'LINKED_ACCOUNT','Values':[binding['scope_id']]}}
    result, warnings, window = [], [], (end-start).days
    token = None
    for _ in range(20):
        args = dict(TimePeriod=period, GroupBy=[{'Type':'DIMENSION','Key':'SUBSCRIPTION_ID'}], Filter=account)
        if token: args['NextPageToken'] = token
        response = client.get_reservation_utilization(**args)
        for period_row in response.get('UtilizationsByTime', []):
            for group in period_row.get('Groups', []):
                a, u = group.get('Attributes') or {}, group.get('Utilization') or {}
                result.append(commitment(provider='aws', scope_id=binding['scope_id'], commitment_id=a.get('leaseId') or group.get('Value'),
                    kind='reservation', name=a.get('instanceType') or a.get('service'), sku=a.get('instanceType'), region=a.get('region'),
                    term=a.get('subscriptionType'), quantity=a.get('numberOfInstances'), status=a.get('subscriptionStatus') or a.get('status'),
                    start=a.get('startDateTime'), end=a.get('endDateTime'), utilization_percent=u.get('UtilizationPercentage'),
                    utilization_window_days=window, commitment_amount=u.get('TotalAmortizedFee'), unused_amount=_unused_ri(u),
                    net_savings=u.get('NetRISavings'), currency='USD'))
        token = response.get('NextPageToken')
        if not token: break
    else: raise ValueError('Reservation pagination limit exceeded')
    token = None
    for _ in range(20):
        args = dict(TimePeriod=period, Filter=account, MaxResults=100)
        if token: args['NextToken'] = token
        response = client.get_savings_plans_utilization_details(**args)
        for row in response.get('SavingsPlansUtilizationDetails', []):
            a, u, s = row.get('Attributes') or {}, row.get('Utilization') or {}, row.get('Savings') or {}
            result.append(commitment(provider='aws', scope_id=binding['scope_id'], commitment_id=row.get('SavingsPlanArn'), kind='savings_plan',
                name=a.get('SavingsPlansType') or 'Savings Plan', sku=a.get('InstanceFamily'), region=a.get('Region'), term=a.get('TermLength') or a.get('PurchaseTerm'),
                status=a.get('Status'), start=a.get('StartDateTime') or a.get('StartDate'), end=a.get('EndDateTime') or a.get('EndDate'), utilization_percent=u.get('UtilizationPercentage'),
                utilization_window_days=window, commitment_amount=u.get('TotalCommitment'), commitment_grain='Period',
                unused_amount=u.get('UnusedCommitment'), net_savings=s.get('NetSavings'), currency='USD'))
        token = response.get('NextToken')
        if not token: break
    else: raise ValueError('Savings Plans pagination limit exceeded')
    coverage = {}
    try:
        reservation = client.get_reservation_coverage(TimePeriod=period, Filter=account).get('Total', {}).get('CoverageHours', {})
        coverage['reservation_hours_percent'] = reservation.get('CoverageHoursPercentage')
        plans = client.get_savings_plans_coverage(TimePeriod=period, Filter=account).get('SavingsPlansCoverages', [])
        spend = [Decimal(str((c.get('Coverage') or {}).get('SpendCoveredBySavingsPlans','0'))) for c in plans]
        total = [Decimal(str((c.get('Coverage') or {}).get('TotalCost','0'))) for c in plans]
        coverage['savings_plan_spend_percent'] = str(round(100*sum(spend)/sum(total),2)) if sum(total) else None
    except Exception:
        warnings.append('Coverage could not be read. Grant ce:GetReservationCoverage and ce:GetSavingsPlansCoverage to include it.')
    if len(result) > MAX_COMMITMENTS: raise ValueError('Commitment limit exceeded')
    return result, coverage, warnings


def _unused_ri(utilization):
    try:
        hours = Decimal(str(utilization['UnusedHours'])); purchased = Decimal(str(utilization['PurchasedHours']))
        fee = Decimal(str(utilization['TotalAmortizedFee']))
        return str(round(fee*hours/purchased, 2)) if purchased else None
    except (KeyError, ArithmeticError, ValueError):
        return None


def gcp_commitments(binding, tenant, start, end):
    from app.cloud_identity import gcp_credentials
    from google.auth.transport.requests import Request
    source = next(x for x in tenant.get('gcp_projects',[]) if x['project_id']==binding['scope_id'])
    credential = gcp_credentials(source, tenant=tenant, scopes=['https://www.googleapis.com/auth/cloud-platform.read-only','https://www.googleapis.com/auth/bigquery'])
    credential.refresh(Request())
    host = 'https://compute.googleapis.com/'
    result, page, warnings = [], None, []
    for _ in range(20):
        body = _get(host+f"compute/v1/projects/{binding['scope_id']}/aggregated/commitments", credential.token,
                    {'maxResults':500, **({'pageToken':page} if page else {})})
        for scope in (body.get('items') or {}).values():
            for row in scope.get('commitments', []):
                resources = row.get('resources') or []
                result.append(commitment(provider='gcp', scope_id=binding['scope_id'], commitment_id=row.get('selfLink') or row.get('id'),
                    kind='committed_use_discount', name=row.get('name'), sku=row.get('type') or row.get('category'),
                    region=str(row.get('region','')).rsplit('/',1)[-1] or None, term=row.get('plan'),
                    quantity=sum((Decimal(str(r.get('amount',0))) for r in resources), Decimal(0)) if resources else None,
                    status=row.get('status'), start=row.get('startTimestamp'), end=row.get('endTimestamp')))
                if len(result) > MAX_COMMITMENTS: raise ValueError('Commitment limit exceeded')
        page = body.get('nextPageToken')
        if not page: break
    else: raise ValueError('Commitment pagination limit exceeded')
    coverage = {}
    try:
        for currency, amount in _gcp_cud_credits(binding, credential.token, start, end).items():
            coverage[f'committed_use_discount_credits_{currency.lower()}'] = amount
    except Exception:
        warnings.append('Committed use discount credits could not be read from the billing export.')
    warnings.append('Compute Engine does not report per-commitment utilization. Applied discount credits come from the billing export.')
    return result, coverage, warnings


def _gcp_cud_credits(binding, token, start, end):
    from app.collectors.billing_sync import _post
    table = '.'.join(binding[k] for k in ('billing_project','dataset','table'))
    query = (f'SELECT currency, SUM(c.amount) FROM `{table}`, UNNEST(credits) c '
             "WHERE project.id=@scope AND c.type='COMMITTED_USAGE_DISCOUNT' AND usage_start_time>=TIMESTAMP(@start) AND usage_start_time<TIMESTAMP(@end) GROUP BY currency")
    parameters = [{'name':name,'parameterType':{'type':'STRING'},'parameterValue':{'value':value}}
                  for name,value in [('scope',binding['scope_id']),('start',start.isoformat()),('end',end.isoformat())]]
    response = _post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{binding['billing_project']}/queries", token,
                     dict(query=query,useLegacySql=False,parameterMode='NAMED',queryParameters=parameters,timeoutMs=20000,maxResults=20,maximumBytesBilled='1000000000'))
    if response.get('jobComplete') is not True: raise ValueError('BigQuery credit query is incomplete')
    return {row['f'][0]['v']: str(-Decimal(str(row['f'][1]['v'] or 0))) for row in response.get('rows', [])}


READERS = {'azure': azure_commitments, 'aws': aws_commitments, 'gcp': gcp_commitments}


def summarize(items, now=None):
    now = now or datetime.now(timezone.utc)
    active = [i for i in items if str(i.get('status') or '').lower() not in ('expired','cancelled','canceled','failed')]
    utilization = [Decimal(i['utilization_percent']) for i in active if i.get('utilization_percent') is not None]
    expiring, unused = 0, {}
    for item in active:
        try:
            ends = datetime.fromisoformat(str(item['end']).replace('Z','+00:00'))
            if ends.tzinfo is None: ends = ends.replace(tzinfo=timezone.utc)
            if now <= ends <= now+timedelta(days=90): expiring += 1
        except (TypeError, ValueError):
            pass
        if item.get('unused_amount') is not None:
            currency = item.get('currency') or 'USD'
            unused[currency] = str(Decimal(unused.get(currency,'0')) + Decimal(item['unused_amount']))
    return dict(active=len(active), total=len(items), expiring_90_days=expiring,
                average_utilization_percent=str(round(sum(utilization)/len(utilization),1)) if utilization else None,
                unused_commitment_cost=unused)
