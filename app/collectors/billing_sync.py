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
from app.v150_store import WorkflowStore

MAX_ROWS = 200000
OPTIONAL_KEYS = {'billing_project','dataset','table','export_type','athena_region','athena_workgroup','athena_database','athena_table'}
NAME = r'[A-Za-z0-9_-]{1,100}'


def bindings(tenant):
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
        if item.get('provider') not in ('azure','aws','gcp') or not authorized(item['provider'], item.get('scope_id',''), tenant):
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


def _post(url, token, body):
    import time
    with httpx.Client(timeout=httpx.Timeout(25, connect=5), follow_redirects=False) as client:
        for attempt in range(8):
            with client.stream('POST', url, headers={'Authorization':'Bearer '+token}, json=body) as response:
                if response.status_code == 429 and attempt < 7:
                    response.read()
                    try: wait = min(float(response.headers.get('retry-after', 5)), 120)
                    except ValueError: wait = 5
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 4_000_000:
                        raise ValueError('Billing response exceeds the limit')
                return json.loads(raw,parse_float=Decimal)


def _azure_query(url, token, kind, start, end):
    import time
    body = dict(type=kind, timeframe='Custom',
        timePeriod={'from':start.isoformat()+'T00:00:00Z','to':(end-timedelta(days=1)).isoformat()+'T23:59:59Z'},
        dataset={'granularity':'Daily','aggregation':{'cost':{'name':'PreTaxCost','function':'Sum'}},
                 'grouping':[{'type':'Dimension','name':'ResourceId'}]})
    rows, page = [], url
    for i in range(100):
        if i: time.sleep(60)  # one page (batch of resources) per minute, matching Azure's observed per-entity quota recovery rate
        properties = _post(page, token, body)['properties']
        names = [c['name'].lower() for c in properties['columns']]
        rows.extend(dict(zip(names,row)) for row in properties['rows'])
        if len(rows) > MAX_ROWS: raise ValueError('Billing row limit exceeded')
        page = properties.get('nextLink')
        if not page: return rows
        if not page.startswith('https://management.azure.com/'): raise ValueError('Unexpected billing pagination host')
    raise ValueError('Billing pagination limit exceeded')


def azure_rows(binding, tenant, start, end):
    import time
    from app.cloud_identity import azure_credential
    credential = azure_credential(tenant)
    try:
        token = credential.get_token('https://management.azure.com/.default').token
        url = f"https://management.azure.com/subscriptions/{binding['scope_id']}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
        merged = {}
        for i, (kind, field) in enumerate((('ActualCost','billed'),('AmortizedCost','effective'))):
            if i: time.sleep(60)  # same per-minute pace between the two cost-kind queries
            for value in _azure_query(url, token, kind, start, end):
                key = (datetime.strptime(str(value['usagedate']), '%Y%m%d').date(), value.get('resourceid') or None, value['currency'])
                totals = merged.setdefault(key, {'billed':Decimal(0),'effective':Decimal(0)})
                totals[field] += Decimal(str(value.get('pretaxcost',value.get('cost'))))
        result = [dict(day=day, resource_id=resource, currency=currency, billed=str(v['billed']), effective=str(v['effective']),
                       category='Credit' if v['billed']<0 else 'Usage') for (day,resource,currency),v in merged.items()]
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
        token = credential.get_token('https://management.azure.com/.default').token
        url = f"https://management.azure.com/subscriptions/{scope_id}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
        merged = {}
        for i, (kind, field) in enumerate((('ActualCost', 'billed'), ('AmortizedCost', 'effective'))):
            if i: time.sleep(5)
            body = dict(type=kind, timeframe='Custom',
                timePeriod={'from': start.isoformat() + 'T00:00:00Z', 'to': (end - timedelta(days=1)).isoformat() + 'T23:59:59Z'},
                dataset={'granularity': 'Daily', 'aggregation': {'cost': {'name': 'PreTaxCost', 'function': 'Sum'}},
                         'filter': {'dimensions': {'name': 'ResourceId', 'operator': 'In', 'values': [resource_id]}}})
            properties = _post(url, token, body)['properties']
            names = [c['name'].lower() for c in properties['columns']]
            for value in (dict(zip(names, row)) for row in properties['rows']):
                key = (datetime.strptime(str(value['usagedate']), '%Y%m%d').date(), value.get('resourceid') or resource_id, value['currency'])
                totals = merged.setdefault(key, {'billed': Decimal(0), 'effective': Decimal(0)})
                totals[field] += Decimal(str(value.get('pretaxcost', value.get('cost'))))
        return [dict(day=day, resource_id=resource, currency=currency, billed=str(v['billed']), effective=str(v['effective']),
                    category='Credit' if v['billed'] < 0 else 'Usage') for (day, resource, currency), v in merged.items()]
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
                             billed=billed or '0', effective=effective or '0', category=CUR_CATEGORIES.get(kind,'Usage')))
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
                        category={'Tax':'Tax','Credit':'Credit','Refund':'Adjustment','Fee':'Purchase'}.get(kind,'Usage')))
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
                         billed=billed,effective=effective,category={'tax':'Tax','adjustment':'Adjustment'}.get(kind,'Usage')))
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
            value=Decimal(str(row[field]))
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
