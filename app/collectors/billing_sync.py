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


def bindings(tenant):
    try:raw = json.loads(os.getenv('CLOUDSAVER_BILLING_CONNECTORS', '[]'))
    except ValueError:raise FocusError('Invalid operator billing connector configuration',503) from None
    if not isinstance(raw, list) or len(raw) > 200:
        raise FocusError('Invalid operator billing connector configuration', 503)
    result = []
    for item in raw:
        if (not isinstance(item, dict) or not {'tenant_id','provider','scope_id'}<=item.keys()
                or set(item)-{'tenant_id','provider','scope_id','billing_project','dataset','table'}
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
        if item['provider'] == 'gcp' and not all(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', item.get(k,'')) for k in ('billing_project','dataset','table')):
            raise FocusError('GCP billing requires an approved BigQuery project, dataset and table', 503)
        result.append(item)
    if len({(x['provider'],x['scope_id']) for x in result}) != len(result):
        raise FocusError('Duplicate billing scope configuration', 503)
    return result


def _post(url, token, body):
    with httpx.Client(timeout=httpx.Timeout(25, connect=5), follow_redirects=False) as client:
        with client.stream('POST', url, headers={'Authorization':'Bearer '+token}, json=body) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > 4_000_000:
                    raise ValueError('Billing response exceeds the limit')
            return json.loads(raw,parse_float=Decimal)


def azure_rows(binding, tenant, start, end):
    from app.cloud_identity import azure_credential
    credential = azure_credential(tenant)
    try:
        token = credential.get_token('https://management.azure.com/.default').token
        url = f"https://management.azure.com/subscriptions/{binding['scope_id']}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
        response = _post(url, token, dict(type='ActualCost', timeframe='Custom',
            timePeriod={'from':start.isoformat()+'T00:00:00Z','to':(end-timedelta(days=1)).isoformat()+'T23:59:59Z'},
            dataset={'granularity':'Daily','aggregation':{'cost':{'name':'PreTaxCost','function':'Sum'}},
                     'grouping':[{'type':'Dimension','name':'ResourceId'}]}))
        properties = response['properties']
        if properties.get('nextLink'):
            raise ValueError('Billing response requires pagination; narrow the configured billing window')
        names = [c['name'].lower() for c in properties['columns']]
        result = []
        for row in properties['rows']:
            value = dict(zip(names,row))
            day = datetime.strptime(str(value['usagedate']), '%Y%m%d').date()
            amount = str(value.get('pretaxcost',value.get('cost')))
            result.append(dict(day=day, resource_id=value.get('resourceid') or None, currency=value['currency'],
                               billed=amount, effective=amount, category='Credit' if Decimal(amount)<0 else 'Usage'))
        return result, 'resource', ['Azure ActualCost is imported; amortized attribution is not verified.']
    finally:
        credential.close()


def aws_rows(binding, tenant, start, end):
    from app.cloud_identity import aws_session
    from botocore.config import Config
    source = next(x for x in tenant.get('aws_accounts',[]) if x['account_id']==binding['scope_id'])
    session = aws_session(source, tenant=tenant)
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
    query=(f'SELECT DATE(usage_start_time) AS day, currency, cost_type, SUM(cost) AS billed, '
           f'SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c),0)) AS effective FROM `{table}` '
           'WHERE project.id=@scope AND usage_start_time>=TIMESTAMP(@start) AND usage_start_time<TIMESTAMP(@end) '
           'GROUP BY day,currency,cost_type ORDER BY day,currency,cost_type')
    parameters=[{'name':name,'parameterType':{'type':'STRING'},'parameterValue':{'value':value}}
                for name,value in [('scope',binding['scope_id']),('start',start.isoformat()),('end',end.isoformat())]]
    response=_post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{binding['billing_project']}/queries",credential.token,
                   dict(query=query,useLegacySql=False,parameterMode='NAMED',queryParameters=parameters,
                        timeoutMs=20000,maxResults=5000,maximumBytesBilled='1000000000'))
    if response.get('jobComplete') is not True or response.get('pageToken') or int(response.get('totalRows',0))>5000:
        raise ValueError('BigQuery billing query is incomplete or exceeds the bounded result limit')
    rows=[]
    for row in response.get('rows',[]):
        day,currency,kind,billed,effective=[x['v'] for x in row['f']]
        rows.append(dict(day=datetime.fromisoformat(day).date(),resource_id=None,currency=currency,
                         billed=billed,effective=effective,category={'tax':'Tax','adjustment':'Adjustment'}.get(kind,'Usage')))
    return rows, 'project', ['Standard BigQuery billing export is project-level; resource-level attribution and export completeness remain unverified.']


READERS={'azure':azure_rows,'aws':aws_rows,'gcp':gcp_rows}


def _import_snapshot(repository, tenant, binding, observations, start, end, currency):
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
    charges=[]
    for (day,resource,category),actual in grouped.items():
        logical='auto:'+digest([binding['provider'],binding['scope_id'],str(day),resource,category])[:48]
        with repository.store.transaction(tenant['tenant_id']) as db:
            prior=db.execute('SELECT charge_id,billed_cost,effective_cost FROM focus_charges WHERE tenant_id=%s '
                'AND provider=%s AND sub_account=%s AND currency=%s AND charge_id LIKE %s',
                (tenant['tenant_id'],binding['provider'],binding['scope_id'],currency,logical+':%')).fetchall()
        previous=[sum((Decimal(str(r[i])) for r in prior),Decimal(0)) for i in (1,2)]
        amounts=[actual[i]-previous[i] for i in (0,1)]
        if prior and not any(amounts): continue
        version=digest([list(map(str,actual)),sorted(str(r[0]) for r in prior)])[:24]
        charges.append(Charge(x_ChargeId=logical+':'+version,ProviderName={'azure':'Azure','aws':'AWS','gcp':'Google Cloud'}[binding['provider']],
            BillingAccountId=binding['scope_id'],SubAccountId=binding['scope_id'],BillingCurrency=currency,
            ChargePeriodStart=datetime.combine(day,datetime.min.time(),timezone.utc),
            ChargePeriodEnd=datetime.combine(day+timedelta(days=1),datetime.min.time(),timezone.utc),ResourceId=resource,
            ChargeCategory='Adjustment' if prior else category,BilledCost=str(amounts[0]),EffectiveCost=str(amounts[1])))
    source='auto-sync:'+digest([binding, str(start),str(end),currency,[c.model_dump(mode='json') for c in charges]])[:64]
    if not charges: return dict(inserted=0,records=0,cached=True)
    return repository.import_records(tenant,ImportRequest(source_id=source,provider=binding['provider'],sub_account_id=binding['scope_id'],
        billing_currency=currency,period_start=start,period_end=end,complete=False,records=charges))


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
            if len(observations)>5000: raise ValueError('Billing row limit exceeded')
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
    return dict(automatic_sync_enabled=bool(selected) and os.getenv('CLOUDSAVER_AUTO_BILLING_SYNC','true').lower()=='true',
                configured=bool(selected),manual_upload_required=False,connectors=[{k:r[k] for k in ('provider','scope_id')} for r in selected],
                recent_syncs=rows,last_synced_at=next((r['updated_at'] for r in rows if r['state']=='completed'),None),
                warning='Only provider-reported charges are imported. Missing coverage and reconciliation remain unknown.')
