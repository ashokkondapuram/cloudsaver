"""Bounded keyless cloud billing readers. Retail prices are never billed charges."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
from uuid import UUID

import httpx

from app.focus import Charge, FocusError, ImportRequest, authorized, digest
from app.provider_retry import ProviderDeferred
from app.v150_store import WorkflowStore
from app.azure_rest_catalog import cost_management_query_path_lower, cost_management_query_url
from app.collectors.azure_endpoint import ARM_HOST

MAX_ROWS = 200000
OPTIONAL_KEYS = {'billing_project','dataset','table','export_type','athena_region','athena_workgroup','athena_database','athena_table'}
COST_SOURCE_ACTUAL_BILLED = 'ACTUAL_BILLED'
COST_SOURCE_FOCUS_IMPORT = 'FOCUS_IMPORT'
COST_SOURCE_RETAIL_ESTIMATED = 'RETAIL_ESTIMATED'


NAME = r'[A-Za-z0-9_-]{1,100}'


def _azure_cost_pacing():
    """Pacing for Cost Management query POSTs.

    Local development uses no artificial spacing so billing import can finish in one pass.
    Production keeps the configured interval; each HTTP attempt gets a deadline that exceeds
    the spacing budget so read_json does not defer before the first byte is sent.
    """
    if os.getenv('CLOUDSAVER_ENVIRONMENT', '').lower() == 'development':
        interval = 0.0
    else:
        interval = max(0.0, min(float(os.getenv('CLOUDSAVER_AZURE_COST_INTERVAL_SECONDS', '15')), 60.0))
    deadline_seconds = min(300, max(120, int(interval) + 90))
    return interval, deadline_seconds


def bindings(tenant, *, require_workspace_scope=True):
    try:raw = json.loads(os.getenv('CLOUDSAVER_BILLING_CONNECTORS', '[]'))
    except ValueError:raise FocusError('Invalid operator billing connector configuration',503) from None
    if not isinstance(raw, list) or len(raw) > 200:
        raise FocusError('Invalid operator billing connector configuration', 503)
    result = []
    for item in raw:
        if (not isinstance(item, dict) or not {'tenant_id','provider','scope_id'}<=item.keys()
                or set(item)-{'tenant_id','provider','scope_id'}-OPTIONAL_KEYS
                or any(not isinstance(v,str) for v in item.values())):
            raise FocusError('Invalid operator billing connector configuration', 503)
        try:owner=str(UUID(item['tenant_id']))
        except ValueError:raise FocusError('Invalid billing connector owner',503) from None
        if owner != tenant['tenant_id']:
            continue
        item=dict(item)
        if item['provider']=='azure':
            try:item['scope_id']=str(UUID(item['scope_id']))
            except ValueError:raise FocusError('Invalid Azure billing scope',503) from None
        if item.get('provider') not in ('azure','aws','gcp'):
            continue
        if require_workspace_scope and not authorized(item['provider'], item.get('scope_id',''), tenant):
            continue
        if item['provider'] == 'gcp' and not all(re.fullmatch(NAME, item.get(k,'')) for k in ('billing_project','dataset','table')):
            raise FocusError('GCP billing requires an approved BigQuery project, dataset and table', 503)
        if item.get('export_type','standard') not in ('standard','detailed') or (item.get('export_type') and item['provider']!='gcp'):
            raise FocusError('export_type applies only to Google Cloud and must be standard or detailed', 503)
        athena=[k for k in ('athena_region','athena_workgroup','athena_database','athena_table') if k in item]
        if athena and (item['provider']!='aws' or len(athena)!=4 or not re.fullmatch(r'[a-z]{2}(-[a-z]+)+-\d',item['athena_region'])
                       or not all(re.fullmatch(NAME,item[k]) for k in athena[1:])):
            raise FocusError('AWS CUR 2.0 billing requires an approved Athena region, workgroup, database and table', 503)
        result.append(item)
    if len({(x['provider'],x['scope_id']) for x in result}) != len(result):
        raise FocusError('Duplicate billing scope configuration', 503)
    return result


def _post(url, token, body, scope_id=None):
    from urllib.parse import urlsplit
    from app.provider_retry import read_json
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Unexpected billing destination')
    azure=parsed.netloc=='management.azure.com'
    if azure:
        scope_id=str(UUID(scope_id))
        expected='/subscriptions/'+scope_id+'/providers/microsoft.costmanagement/query'
        if parsed.path.lower()!=expected:raise ValueError('Unexpected billing scope')
        key='azure:cost:'+scope_id
        interval, deadline_seconds = _azure_cost_pacing()
        raw_attempts = os.getenv(
            'CLOUDSAVER_AZURE_COST_MANAGEMENT_ATTEMPTS',
            '5' if os.getenv('CLOUDSAVER_ENVIRONMENT', '').lower() == 'development' else '3',
        )
        attempts = min(5, int(raw_attempts))
        if not 1 <= int(raw_attempts) <= 12:
            raise ValueError('CLOUDSAVER_AZURE_COST_MANAGEMENT_ATTEMPTS must be between 1 and 12')
    elif parsed.netloc=='bigquery.googleapis.com' and re.fullmatch(r'/bigquery/v2/projects/[a-z][a-z0-9-]{4,61}[a-z0-9]/queries',parsed.path):
        key='gcp:bigquery:'+parsed.path.split('/')[4]
        interval=0
        deadline_seconds=30
        raw_attempts = os.getenv('CLOUDSAVER_GCP_BIGQUERY_ATTEMPTS', '3')
        attempts = min(5, int(raw_attempts))
        if not 1 <= int(raw_attempts) <= 12:
            raise ValueError('CLOUDSAVER_GCP_BIGQUERY_ATTEMPTS must be between 1 and 12')
    else:raise ValueError('Unexpected billing destination')
    with httpx.Client(follow_redirects=False) as client:
        return read_json(client,'POST',url,headers={'Authorization':'Bearer '+token},json=body,
            quota_key=key,interval=interval,read_only_post=True,max_bytes=4_000_000,
            parse_float=Decimal,attempts=attempts,deadline_seconds=deadline_seconds)


def _token(credential):
    """Refresh (or return the still-valid cached) token; azure-identity only hits the network when near expiry.
    Retries transient DNS/connection failures so an hours-long paced sync survives a momentary network blip."""
    import time
    for attempt in range(4):
        try:
            return credential.get_token('https://management.azure.com/.default').token
        except Exception:
            if attempt == 3: raise
            time.sleep(10)


def _azure_query(url, credential, kind, start, end, scope_id):
    body = dict(type=kind, timeframe='Custom',
        timePeriod={'from':start.isoformat()+'T00:00:00Z','to':(end-timedelta(days=1)).isoformat()+'T23:59:59Z'},
        dataset={'granularity':'Daily','aggregation':{'cost':{'name':'PreTaxCost','function':'Sum'}},
                 'grouping':[{'type':'Dimension','name':'ResourceId'}]})
    rows, page, seen = [], url, {url}
    for i in range(100):
        properties = _post(page, _token(credential), body, scope_id)['properties']
        names = [c['name'].lower() for c in properties['columns']]
        rows.extend(dict(zip(names,row)) for row in properties['rows'])
        if len(rows) > MAX_ROWS: raise ValueError('Billing row limit exceeded')
        page = properties.get('nextLink')
        if not page: return rows
        from urllib.parse import urlsplit
        parsed=urlsplit(page)
        expected = cost_management_query_path_lower(scope_id)
        if (page in seen or parsed.scheme!='https' or parsed.netloc!=ARM_HOST
            or parsed.fragment or parsed.path.lower()!=expected):
            raise ValueError('Unexpected billing pagination host, scope or repeated cursor')
        seen.add(page)
    raise ValueError('Billing pagination limit exceeded')


def _cost_merge_key(value, resource_id):
    day = datetime.strptime(str(value['usagedate']), '%Y%m%d').date()
    resource = value.get('resourceid') or resource_id
    return day, resource, value['currency']


def _accumulate_cost_amount(merged, key, field, amount):
    totals = merged.setdefault(
        key,
        dict(billed=None, effective=None, billed_present=False, effective_present=False),
    )
    current = totals[field] or Decimal(0)
    totals[field] = current + amount
    totals[f'{field}_present'] = True


def _cost_row_from_totals(day, resource, currency, totals, *, cost_source=COST_SOURCE_ACTUAL_BILLED):
    billed = totals['billed']
    return dict(
        day=day,
        resource_id=resource.lower() if isinstance(resource, str) and resource.lower().startswith('/subscriptions/') else resource,
        currency=currency,
        billed=str(billed) if totals['billed_present'] else None,
        effective=str(totals['effective']) if totals['effective_present'] else None,
        billed_present=totals['billed_present'],
        effective_present=totals['effective_present'],
        category='Credit' if totals['billed_present'] and billed is not None and billed < 0 else 'Usage',
        cost_source=cost_source,
    )


def focus_import_observation_row(day, resource_id, currency, *, billed, effective, category='Usage'):
    """Internal billing row for operator FOCUS/manual imports (not provider auto-sync)."""
    return dict(
        day=day,
        resource_id=resource_id.lower() if isinstance(resource_id, str) and resource_id.lower().startswith('/subscriptions/') else resource_id,
        currency=currency,
        billed=str(billed) if billed is not None else None,
        effective=str(effective) if effective is not None else None,
        billed_present=billed is not None,
        effective_present=effective is not None,
        category=category,
        cost_source=COST_SOURCE_FOCUS_IMPORT,
    )


def retail_estimated_observation_row(day, resource_id, currency, *, billed, effective=None, category='Usage'):
    """Internal billing row when only a retail/list estimate is available (not provider-billed)."""
    return dict(
        day=day,
        resource_id=resource_id.lower() if isinstance(resource_id, str) and resource_id.lower().startswith('/subscriptions/') else resource_id,
        currency=currency,
        billed=str(billed) if billed is not None else None,
        effective=str(effective) if effective is not None else None,
        billed_present=billed is not None,
        effective_present=effective is not None,
        category=category,
        cost_source=COST_SOURCE_RETAIL_ESTIMATED,
    )


def _azure_resource_query(url, credential, kind, start, end, scope_id, resource_id):
    """Single-resource CM filter query; subscription-wide queries paginate in _azure_query instead."""
    body = dict(
        type=kind,
        timeframe='Custom',
        timePeriod={
            'from': start.isoformat() + 'T00:00:00Z',
            'to': (end - timedelta(days=1)).isoformat() + 'T23:59:59Z',
        },
        dataset={
            'granularity': 'Daily',
            'aggregation': {'cost': {'name': 'PreTaxCost', 'function': 'Sum'}},
            'filter': {'dimensions': {'name': 'ResourceId', 'operator': 'In', 'values': [resource_id]}},
        },
    )
    properties = _post(url, _token(credential), body, scope_id)['properties']
    if properties.get('nextLink'):
        raise ValueError(
            'Azure per-resource Cost Management query is incomplete; continuation pages are not imported'
        )
    names = [c['name'].lower() for c in properties['columns']]
    return [dict(zip(names, row)) for row in properties['rows']]


def azure_rows(binding, tenant, start, end):
    import time
    from app.cloud_identity import azure_credential
    credential = azure_credential(tenant)
    try:
        url = cost_management_query_url(binding['scope_id'])
        merged = {}
        for i, (kind, field) in enumerate((('ActualCost','billed'),('AmortizedCost','effective'))):
            for value in _azure_query(url, credential, kind, start, end, binding['scope_id']):
                key = (datetime.strptime(str(value['usagedate']), '%Y%m%d').date(), value.get('resourceid') or None, value['currency'])
                amount = Decimal(str(value.get('pretaxcost', value.get('cost'))))
                _accumulate_cost_amount(merged, key, field, amount)
        result = [
            _cost_row_from_totals(day, resource, currency, v)
            for (day, resource, currency), v in merged.items()
        ]
        return result, 'resource', ['Azure ActualCost is imported as billed cost and AmortizedCost as effective cost. Reservation and savings plan purchases are spread across covered usage.']
    finally:
        credential.close()


def azure_resource_rows(scope_id, resource_id, tenant, start, end):
    """Daily cost rows for exactly one resource, filtered (not grouped) so it stays tiny regardless of subscription size.

    Returned in the same shape as azure_rows so callers can persist through _import_snapshot like a normal sync."""
    import time
    from app.cloud_identity import azure_credential
    credential = azure_credential(tenant)
    try:
        url = cost_management_query_url(scope_id)
        merged = {}
        for kind, field in (('ActualCost', 'billed'), ('AmortizedCost', 'effective')):
            for value in _azure_resource_query(url, credential, kind, start, end, scope_id, resource_id):
                key = _cost_merge_key(value, resource_id)
                amount = Decimal(str(value.get('pretaxcost', value.get('cost'))))
                _accumulate_cost_amount(merged, key, field, amount)
        return [_cost_row_from_totals(day, resource, currency, v) for (day, resource, currency), v in merged.items()]
    finally:
        credential.close()


CUR_CATEGORIES = {'Tax':'Tax','Credit':'Credit','Refund':'Adjustment','Fee':'Purchase','RIFee':'Purchase',
                  'SavingsPlanRecurringFee':'Purchase','SavingsPlanUpfrontFee':'Purchase'}
CUR_EFFECTIVE = ("CASE line_item_line_item_type WHEN 'SavingsPlanCoveredUsage' THEN savings_plan_savings_plan_effective_cost "
    "WHEN 'SavingsPlanRecurringFee' THEN savings_plan_total_commitment_to_date - savings_plan_used_commitment "
    "WHEN 'SavingsPlanNegation' THEN 0 WHEN 'SavingsPlanUpfrontFee' THEN 0 "
    "WHEN 'DiscountedUsage' THEN reservation_effective_cost "
    "WHEN 'RIFee' THEN reservation_unused_amortized_upfront_fee_for_billing_period + reservation_unused_recurring_fee "
    "WHEN 'Fee' THEN CASE WHEN reservation_reservation_a_r_n <> '' THEN 0 ELSE line_item_unblended_cost END "
    "ELSE line_item_unblended_cost END")


def athena_rows(session, binding, start, end, *, sleep=None, max_wait_seconds=120):
    """CUR 2.0 per-resource daily charges with AWS amortization fields; parameters are bound, identifiers are allowlisted."""
    import time
    from botocore.config import Config
    sleep = sleep or time.sleep
    client = session.client('athena', region_name=binding['athena_region'], config=Config(connect_timeout=5,read_timeout=25,retries={'total_max_attempts':1}))
    query = (f"SELECT CAST(DATE(line_item_usage_start_date) AS VARCHAR), line_item_resource_id, line_item_currency_code, line_item_line_item_type, "
             f"SUM(line_item_unblended_cost), SUM({CUR_EFFECTIVE}) "
             f'FROM "{binding["athena_database"]}"."{binding["athena_table"]}" '
             "WHERE line_item_usage_account_id = ? AND line_item_usage_start_date >= CAST(? AS TIMESTAMP) AND line_item_usage_start_date < CAST(? AS TIMESTAMP) "
             "GROUP BY 1, 2, 3, 4")
    started = client.start_query_execution(QueryString=query, WorkGroup=binding['athena_workgroup'],
        QueryExecutionContext={'Database':binding['athena_database']},
        ExecutionParameters=[f"'{binding['scope_id']}'", f"'{start.isoformat()} 00:00:00'", f"'{end.isoformat()} 00:00:00'"])
    execution = started['QueryExecutionId']
    for _ in range(max_wait_seconds):
        state = client.get_query_execution(QueryExecutionId=execution)['QueryExecution']['Status']['State']
        if state == 'SUCCEEDED': break
        if state in ('FAILED','CANCELLED'): raise ValueError('Athena billing query did not succeed')
        sleep(1)
    else:
        client.stop_query_execution(QueryExecutionId=execution)
        raise ValueError('Athena billing query exceeded the bounded wait')
    rows, token, header = [], None, True
    for _ in range(MAX_ROWS // 1000 + 2):
        args = dict(QueryExecutionId=execution, MaxResults=1000)
        if token: args['NextToken'] = token
        page = client.get_query_results(**args)
        for row in page['ResultSet']['Rows']:
            if header: header = False; continue
            day, resource, currency, kind, billed, effective = [c.get('VarCharValue') for c in row['Data']]
            if not Decimal(billed or '0') and not Decimal(effective or '0'): continue
            rows.append(dict(day=datetime.fromisoformat(day).date(), resource_id=resource or None, currency=currency,
                             billed=billed or '0', effective=effective or '0', category=CUR_CATEGORIES.get(kind,'Usage'),
                             cost_source=COST_SOURCE_ACTUAL_BILLED))
            if len(rows) > MAX_ROWS: raise ValueError('Billing row limit exceeded')
        token = page.get('NextToken')
        if not token: return rows
    raise ValueError('Athena billing pagination limit exceeded')


def aws_rows(binding, tenant, start, end):
    from app.cloud_identity import aws_session
    from botocore.config import Config
    source = next(x for x in tenant.get('aws_accounts',[]) if x['account_id']==binding['scope_id'])
    session = aws_session(source, tenant=tenant)
    if binding.get('athena_table'):
        return athena_rows(session, binding, start, end), 'resource', ['CUR 2.0 line items are summed per resource and day. Effective cost follows the AWS amortization fields for Reserved Instances and Savings Plans.']
    client = session.client('ce', region_name='us-east-1', config=Config(connect_timeout=5,read_timeout=25,retries={'total_max_attempts':1}))
    result, token = [], None
    try:
        for _ in range(10):
            args = dict(TimePeriod={'Start':start.isoformat(),'End':end.isoformat()}, Granularity='DAILY',
                        Metrics=['UnblendedCost','AmortizedCost'],GroupBy=[{'Type':'DIMENSION','Key':'RECORD_TYPE'}],
                        Filter={'Dimensions':{'Key':'LINKED_ACCOUNT','Values':[binding['scope_id']]}})
            if token: args['NextPageToken'] = token
            response = client.get_cost_and_usage(**args)
            for period in response['ResultsByTime']:
                for group in period.get('Groups',[]):
                    costs=group['Metrics']; actual=costs['UnblendedCost']; effective=costs['AmortizedCost']
                    if effective['Unit'] != actual['Unit']: raise ValueError('Currency mismatch')
                    kind=group['Keys'][0]
                    result.append(dict(day=datetime.fromisoformat(period['TimePeriod']['Start']).date(),resource_id=None,
                        currency=actual['Unit'],billed=actual['Amount'],effective=effective['Amount'],
                        category={'Tax':'Tax','Credit':'Credit','Refund':'Adjustment','Fee':'Purchase'}.get(kind,'Usage'),
                        cost_source=COST_SOURCE_ACTUAL_BILLED))
            token=response.get('NextPageToken')
            if not token: break
        else: raise ValueError('Billing pagination limit exceeded')
        return result, 'account', ['Cost Explorer amounts are account-level; no per-resource charge or export-completeness proof is invented.']
    finally:
        client.close()


def gcp_rows(binding, tenant, start, end):
    from app.cloud_identity import gcp_credentials
    from google.auth.transport.requests import Request
    source=next(x for x in tenant.get('gcp_projects',[]) if x['project_id']==binding['scope_id'])
    credential=gcp_credentials(source,tenant=tenant,scopes=['https://www.googleapis.com/auth/bigquery'])
    credential.refresh(Request())
    table='.'.join(binding[k] for k in ('billing_project','dataset','table'))
    detailed=binding.get('export_type')=='detailed'
    resource='resource.global_name' if detailed else 'CAST(NULL AS STRING)'
    query=(f'SELECT DATE(usage_start_time) AS day, currency, cost_type, {resource} AS resource_id, SUM(cost) AS billed, '
           f'SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c),0)) AS effective FROM `{table}` '
           'WHERE project.id=@scope AND usage_start_time>=TIMESTAMP(@start) AND usage_start_time<TIMESTAMP(@end) '
           'GROUP BY day,currency,cost_type,resource_id ORDER BY day,currency,cost_type,resource_id')
    parameters=[{'name':name,'parameterType':{'type':'STRING'},'parameterValue':{'value':value}}
                for name,value in [('scope',binding['scope_id']),('start',start.isoformat()),('end',end.isoformat())]]
    response=_post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{binding['billing_project']}/queries",credential.token,
                   dict(query=query,useLegacySql=False,parameterMode='NAMED',queryParameters=parameters,
                        timeoutMs=20000,maxResults=MAX_ROWS,maximumBytesBilled='5000000000' if detailed else '1000000000'))
    if response.get('jobComplete') is not True or response.get('pageToken') or int(response.get('totalRows',0))>MAX_ROWS:
        raise ValueError('BigQuery billing query is incomplete or exceeds the bounded result limit')
    rows=[]
    for row in response.get('rows',[]):
        day,currency,kind,resource_id,billed,effective=[x['v'] for x in row['f']]
        rows.append(dict(day=datetime.fromisoformat(day).date(),resource_id=resource_id or None,currency=currency,
                         billed=billed,effective=effective,category={'tax':'Tax','adjustment':'Adjustment'}.get(kind,'Usage'),
                         cost_source=COST_SOURCE_ACTUAL_BILLED))
    if detailed:
        return rows, 'resource', ['The detailed BigQuery billing export is summed per resource and day. Export completeness remains unverified.']
    return rows, 'project', ['Standard BigQuery billing export is project-level; resource-level attribution and export completeness remain unverified.']


READERS={'azure':azure_rows,'aws':aws_rows,'gcp':gcp_rows}


def _import_snapshot(repository, tenant, binding, observations, start, end, currency, *, authoritative=False, watermark=None, _db=None):
    """Append exact correction deltas; immutable charge rows are never overwritten."""
    grouped={}
    for row in observations:
        if row['currency'] != currency: continue
        if not start <= row['day'] < end: raise ValueError('Provider returned an out-of-window charge')
        key=(row['day'],row.get('resource_id'),row['category'])
        totals=grouped.setdefault(key,[Decimal(0),Decimal(0)])
        for i,field in enumerate(('billed','effective')):
            raw=row.get(field)
            if raw is None:
                continue
            value=Decimal(str(raw))
            if not value.is_finite() or abs(value)>Decimal('1e15'): raise ValueError('Invalid provider amount')
            totals[i]+=value
    from contextlib import nullcontext
    if authoritative and (not isinstance(watermark,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',watermark)):
        raise ValueError('An authoritative snapshot needs a source-native watermark')
    requested={}
    for (day,resource,category),actual in grouped.items():
        logical='auto:'+digest([binding['provider'],binding['scope_id'],str(day),resource,category])[:48]
        requested[logical]=(day,resource,category,actual)
    with (nullcontext(_db) if _db is not None else repository.store.transaction(tenant['tenant_id'])) as db:
        old=db.execute('SELECT charge_id,period_start,resource_id,billed_cost,effective_cost FROM focus_charges WHERE tenant_id=%s '
            'AND provider=%s AND sub_account=%s AND currency=%s AND charge_id LIKE %s AND period_start>=%s AND period_start<%s LIMIT 50001',
            (tenant['tenant_id'],binding['provider'],binding['scope_id'],currency,'auto:%',str(start),str(end))).fetchall()
    if len(old)>50000:raise ValueError('Prior snapshot exceeds the reconciliation bound')
    previous={}
    for row in old:
        logical=str(row[0]).rsplit(':',1)[0]
        item=previous.setdefault(logical,dict(ids=[],amounts=[Decimal(0),Decimal(0)],day=datetime.fromisoformat(str(row[1])).date(),resource=row[2]))
        item['ids'].append(str(row[0]));item['amounts'][0]+=Decimal(str(row[3]));item['amounts'][1]+=Decimal(str(row[4]))
    absent={key:value for key,value in previous.items() if key not in requested and any(value['amounts'])}
    if authoritative:
        for key,prior in absent.items():requested[key]=(prior['day'],prior['resource'],'Adjustment',[Decimal(0),Decimal(0)])
    charges=[]
    for logical,(day,resource,category,actual) in requested.items():
        prior=previous.get(logical);amounts=[actual[i]-(prior['amounts'][i] if prior else 0) for i in (0,1)]
        if prior and not any(amounts):continue
        version=digest([list(map(str,actual)),sorted(prior['ids']) if prior else []])[:24]
        charges.append(Charge(x_ChargeId=logical+':'+version,ProviderName={'azure':'Azure','aws':'AWS','gcp':'Google Cloud'}[binding['provider']],
            BillingAccountId=binding['scope_id'],SubAccountId=binding['scope_id'],BillingCurrency=currency,
            ChargePeriodStart=datetime.combine(day,datetime.min.time(),timezone.utc),
            ChargePeriodEnd=datetime.combine(day+timedelta(days=1),datetime.min.time(),timezone.utc),ResourceId=resource,
            ChargeCategory='Adjustment' if prior else category,BilledCost=str(amounts[0]),EffectiveCost=str(amounts[1])))
    source='auto-sync:'+digest([binding,str(start),str(end),currency,[c.model_dump(mode='json') for c in charges]])[:64]
    result=(repository.import_records(tenant,ImportRequest(source_id=source,provider=binding['provider'],sub_account_id=binding['scope_id'],
        billing_currency=currency,period_start=start,period_end=end,complete=False,records=charges),_db=_db)
        if charges else dict(inserted=0,records=0,cached=True))
    return dict(result,unresolved_absent_groups=0 if authoritative else len(absent),
                reconciliation_status='source_snapshot_reconciled' if authoritative else 'unverified',source_watermark=watermark)


def sync_workspace_billing(tenant, repository, *, currency='USD', readers=None):
    enabled=os.getenv('CLOUDSAVER_AUTO_BILLING_SYNC','true').lower()=='true'
    if not enabled: raise FocusError('Automatic billing sync is disabled by the deployment operator',503)
    selected=bindings(tenant)
    if not selected: raise FocusError('No authorized cloud billing connector is configured',503)
    if len(selected)>8: raise FocusError('Configure at most eight billing scopes per bounded synchronization run',422)
    store=WorkflowStore(repository.store)
    run=store.begin(tenant['tenant_id'],'billing_sync_runs','billing-sync',{'currency':currency})
    end=datetime.now(timezone.utc).date()-timedelta(days=2);start=end-timedelta(days=30)
    results=[]
    for binding in selected:
        try:
            observations,granularity,warnings=(readers or READERS)[binding['provider']](binding,tenant,start,end)
            if len(observations)>MAX_ROWS: raise ValueError('Billing row limit exceeded')
            currencies=sorted({r['currency'] for r in observations}) if currency is None else [currency]
            if any(not re.fullmatch(r'[A-Z]{3}',c) for c in currencies):raise ValueError('Invalid billing currency')
            if observations and currency is not None and not any(r['currency']==currency for r in observations):raise ValueError('Requested billing currency is unavailable')
            imports=[_import_snapshot(repository,tenant,binding,observations,start,end,c) for c in currencies]
            imported=dict(inserted=sum(x['inserted'] for x in imports),records=sum(x['records'] for x in imports),cached=all(x.get('cached',False) for x in imports))
            results.append(dict(provider=binding['provider'],scope_id=binding['scope_id'],status='completed',
                                granularity=granularity,coverage_verified=False,warnings=warnings,**imported))
        except ProviderDeferred as deferred:
            results.append(dict(
                provider=binding['provider'], scope_id=binding['scope_id'], status='failed',
                error_code='BILLING_PROVIDER_THROTTLED', retry_after_seconds=deferred.retry_after,
            ))
        except Exception:
            # Provider exceptions can include credentials, resource IDs and response bodies.
            results.append(dict(provider=binding['provider'],scope_id=binding['scope_id'],status='failed',error_code='BILLING_SOURCE_UNAVAILABLE_OR_INVALID'))
    state='completed' if all(r['status']=='completed' for r in results) else 'partial' if any(r['status']=='completed' for r in results) else 'failed'
    response=dict(id=run,status=state,period_start=str(start),period_end=str(end),currency=currency,synced_scopes=results,
                  inserted_records=sum(r.get('inserted',0) for r in results),coverage_verified=False)
    store.finish(tenant['tenant_id'],'billing_sync_runs',run,state,response)
    return response


def sync_status(tenant, repository):
    selected=bindings(tenant)
    rows=WorkflowStore(repository.store).rows(tenant['tenant_id'],'billing_sync_runs')
    with repository.store.transaction(tenant['tenant_id']) as db:
        jobs=db.execute('SELECT id,state,payload,updated_at FROM billing_sync_jobs WHERE tenant_id=%s ORDER BY created_at DESC LIMIT 25',(tenant['tenant_id'],)).fetchall()
    from app.enterprise_store import decode
    rows=[dict(id=str(r[0]),state=r[1],updated_at=str(r[3]),payload=dict(inserted_records=sum(s.get('inserted',0) for s in decode(r[2]).get('scope_results',[])),unresolved_absent_groups=sum(s.get('unresolved_absent_groups',0) for s in decode(r[2]).get('scope_results',[])))) for r in jobs]+rows
    return dict(automatic_sync_enabled=bool(selected) and os.getenv('CLOUDSAVER_AUTO_BILLING_SYNC','true').lower()=='true',
                configured=bool(selected),manual_upload_required=False,connectors=[{k:r[k] for k in ('provider','scope_id')} for r in selected],
                recent_syncs=rows,last_synced_at=next((r['updated_at'] for r in rows if r['state']=='completed'),None),
                warning='Only provider-reported charges are imported. Missing coverage and reconciliation remain unknown.')
