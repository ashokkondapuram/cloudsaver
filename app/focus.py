"""Strict normalized FOCUS billing subset. Imports are evidence, never verified savings."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import math
import re
from typing import Literal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from app.enterprise_store import decode

PROVIDERS={'Azure':'azure','AWS':'aws','Google Cloud':'gcp'}


class FocusError(ValueError):
    def __init__(self,message,status=422):
        super().__init__(message);self.status=status


def money(value):
    # JSON strings preserve decimal precision. Binary floats, booleans, NaN and exponent syntax are not billing amounts.
    if not isinstance(value,str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?',value):
        raise ValueError('Billing amounts require bounded decimal strings')
    result=Decimal(value)
    return format(result.quantize(Decimal('0.00000001')),'f')


class Charge(BaseModel):
    model_config=ConfigDict(extra='forbid')
    x_ChargeId: str = Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_.:/-]+$')
    ProviderName: Literal['Azure','AWS','Google Cloud']
    BillingAccountId: str = Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_.:/-]+$')
    SubAccountId: str = Field(min_length=1,max_length=128)
    BillingCurrency: str = Field(pattern=r'^[A-Z]{3}$')
    ChargePeriodStart: datetime
    ChargePeriodEnd: datetime
    ResourceId: str | None = Field(default=None,max_length=2048)
    ChargeCategory: Literal['Usage','Purchase','Tax','Credit','Adjustment']
    BilledCost: str
    EffectiveCost: str
    ListCost: str | None = None

    @field_validator('BilledCost','EffectiveCost','ListCost',mode='before')
    @classmethod
    def amounts(cls,value):
        return money(value) if value is not None else value

    @field_validator('ChargePeriodStart','ChargePeriodEnd')
    @classmethod
    def timestamp(cls,value):
        if value.tzinfo is None:
            raise ValueError('Charge periods require an explicit timezone')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def interval(self):
        if self.ProviderName=='Azure':
            self.SubAccountId=str(UUID(self.SubAccountId))
            if self.ResourceId: self.ResourceId=self.ResourceId.lower()
        if not timedelta(0)<self.ChargePeriodEnd-self.ChargePeriodStart<=timedelta(days=366):
            raise ValueError('Invalid charge period')
        if self.ListCost is not None and Decimal(self.ListCost)<0:
            raise ValueError('List cost cannot be negative')
        return self


class ImportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_.:-]+$')
    provider: Literal['azure','aws','gcp']
    sub_account_id: str = Field(min_length=1,max_length=128)
    billing_currency: str = Field(pattern=r'^[A-Z]{3}$')
    period_start: date
    period_end: date
    complete: StrictBool
    records: list[Charge] = Field(max_length=5000)

    @model_validator(mode='after')
    def interval(self):
        if self.provider=='azure': self.sub_account_id=str(UUID(self.sub_account_id))
        if not 0<(self.period_end-self.period_start).days<=366:
            raise ValueError('Import periods require 1 to 366 complete UTC days')
        begin=datetime.combine(self.period_start,time.min,tzinfo=timezone.utc)
        end=datetime.combine(self.period_end,time.min,tzinfo=timezone.utc)
        ids=set()
        for row in self.records:
            if (PROVIDERS[row.ProviderName]!=self.provider or row.SubAccountId!=self.sub_account_id
                    or row.BillingCurrency!=self.billing_currency or not begin<=row.ChargePeriodStart<row.ChargePeriodEnd<=end):
                raise ValueError('All records must belong to the declared scope, currency and import period')
            identity=(row.BillingAccountId,row.x_ChargeId)
            if identity in ids:
                raise ValueError('Duplicate charge identity in import')
            ids.add(identity)
        return self


def authorized(provider,account,tenant):
    if provider=='azure':
        try: account=str(UUID(account))
        except ValueError: return False
        return account in tenant.get('subscription_ids',[])
    if provider=='aws': return account in {a['account_id'] for a in tenant.get('aws_accounts',[])}
    return account in {p['project_id'] for p in tenant.get('gcp_projects',[])}


def validate_scope(payload,tenant):
    if not authorized(payload.provider,payload.sub_account_id,tenant):
        raise FocusError('Billing import is outside the current workspace cloud scope',403)
    for row in payload.records:
        resource=row.ResourceId
        if not resource: continue
        if payload.provider=='azure':
            valid=resource.lower().startswith('/subscriptions/'+str(UUID(payload.sub_account_id))+'/')
        elif payload.provider=='aws':
            parts=resource.split(':',5)
            valid=len(parts)==6 and parts[0:2]==['arn','aws'] and parts[4]==payload.sub_account_id
        else:
            valid=resource.startswith(('//compute.googleapis.com/projects/'+payload.sub_account_id+'/',
                '//sqladmin.googleapis.com/projects/'+payload.sub_account_id+'/', 'projects/'+payload.sub_account_id+'/'))
        if not valid:
            raise FocusError('A billing resource does not match its declared cloud account',403)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def utc(value):
    return value.astimezone(timezone.utc) if isinstance(value,datetime) else datetime.fromisoformat(value).astimezone(timezone.utc)


class FocusRepository:
    def __init__(self,store): self.store=store

    def import_records(self,tenant,payload,*,_db=None):
        validate_scope(payload,tenant)
        raw=payload.model_dump(mode='json')
        for row in raw['records']:
            for field in ('ChargePeriodStart','ChargePeriodEnd'):
                row[field]=utc(row[field]).isoformat()
        raw['records'].sort(key=lambda r:(r['BillingAccountId'],r['x_ChargeId']))
        fingerprint=digest(raw);tenant_id=tenant['tenant_id']
        batch_id=str(uuid4());now=datetime.now(timezone.utc).isoformat()
        actor=digest(dict(tenant=tenant_id,user=tenant.get('user_id','workspace_key')))
        from contextlib import nullcontext
        with (nullcontext(_db) if _db is not None else self.store.transaction(tenant_id,write=True)) as db:
            prior=db.execute('SELECT id,fingerprint,records,inserted FROM focus_imports WHERE tenant_id=%s AND source_id=%s',(tenant_id,payload.source_id)).fetchone()
            if prior:
                if prior[1]!=fingerprint: raise FocusError('Source ID already belongs to different billing data',409)
                return dict(import_id=str(prior[0]),records=prior[2],inserted=prior[3],cached=True)
            if db.postgres:
                existing=db.execute('SELECT organization_id FROM tenants WHERE tenant_id=%s',(tenant_id,)).fetchone()
                organization_id=existing[0] if existing else uuid5(NAMESPACE_URL,'cloudsaver:organization:'+tenant_id)
                db.execute('INSERT INTO organizations(id,tenant_id,name) VALUES (%s,%s,%s) ON CONFLICT(id) DO NOTHING',(organization_id,tenant_id,tenant['name']))
                db.execute("INSERT INTO tenants(tenant_id,organization_id,display_name,connection_status) VALUES (%s,%s,%s,'configured') ON CONFLICT(tenant_id) DO NOTHING",(tenant_id,organization_id,tenant['name']))
            pending=[]
            for row in raw['records']:
                record_fingerprint=digest(row)
                prior=db.execute('SELECT fingerprint FROM focus_charges WHERE tenant_id=%s AND provider=%s AND billing_account=%s AND charge_id=%s',
                    (tenant_id,payload.provider,row['BillingAccountId'],row['x_ChargeId'])).fetchone()
                if prior and prior[0]!=record_fingerprint:
                    raise FocusError('An existing charge identity has conflicting evidence; no records were imported',409)
                if not prior: pending.append((row,record_fingerprint))
            db.execute('''INSERT INTO focus_imports(id,tenant_id,source_id,fingerprint,provider,sub_account,currency,period_start,period_end,complete,records,inserted,actor,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (batch_id,tenant_id,payload.source_id,fingerprint,payload.provider,payload.sub_account_id,payload.billing_currency,
                 payload.period_start.isoformat(),payload.period_end.isoformat(),payload.complete,len(raw['records']),len(pending),actor,now))
            for row,record_fingerprint in pending:
                db.execute('''INSERT INTO focus_charges(id,tenant_id,import_id,provider,billing_account,sub_account,charge_id,fingerprint,
                    currency,period_start,period_end,resource_id,charge_category,billed_cost,effective_cost,list_cost)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (str(uuid4()),tenant_id,batch_id,payload.provider,row['BillingAccountId'],row['SubAccountId'],row['x_ChargeId'],record_fingerprint,
                     row['BillingCurrency'],row['ChargePeriodStart'],row['ChargePeriodEnd'],row['ResourceId'],row['ChargeCategory'],row['BilledCost'],row['EffectiveCost'],row['ListCost']))
        return dict(import_id=batch_id,records=len(raw['records']),inserted=len(pending),cached=False)

    def resource_costs(self, tenant, resource_ids, window_days=30, *, as_of=None):
        """Exact resource/scope/currency attribution; never spread account totals across resources."""
        if type(window_days) is not int or not 1 <= window_days <= 90:
            raise FocusError('Resource billing requires a 1–90 day window')
        ids = set(resource_ids)
        if len(ids) > 100000 or any(not isinstance(v,str) or len(v)>2048 for v in ids):
            raise FocusError('Invalid resource billing selection')
        finish = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
        begin = finish - timedelta(days=window_days)
        scopes = [('azure',v) for v in tenant.get('subscription_ids',[])] + [('aws',a['account_id']) for a in tenant.get('aws_accounts',[])] + [('gcp',a['project_id']) for a in tenant.get('gcp_projects',[])]
        allowed = tenant.get('allowed_providers')
        scopes = sorted(set((p,a) for p,a in scopes if allowed is None or p in allowed))
        if not ids or not scopes:return {}
        normalized = {v.lower() if v.lower().startswith('/subscriptions/') else v for v in ids}
        fence = ' OR '.join('(provider=%s AND sub_account=%s)' for _ in scopes)
        args = [v for pair in scopes for v in pair]
        totals = {}
        with self.store.transaction(tenant['tenant_id']) as db:
            coverage = db.execute('SELECT provider,sub_account,period_start,period_end,complete FROM focus_imports WHERE tenant_id=%s AND currency=%s AND ('+fence+') AND period_start<%s AND period_end>%s ORDER BY created_at,id LIMIT 50001',
                [tenant['tenant_id'],'USD',*args,finish.date().isoformat(),begin.date().isoformat()]).fetchall()
            if len(coverage)>50000:raise FocusError('Narrow the resource billing import window')
            days={}
            for provider,account,a,b,complete in coverage:
                day=max(date.fromisoformat(str(a)),begin.date());end=min(date.fromisoformat(str(b)),finish.date())
                while day<end:
                    days.setdefault((provider,account),{})[day]=bool(complete);day+=timedelta(days=1)
            for offset in range(0,len(normalized),300):
                selected=sorted(normalized)[offset:offset+300]
                marks=','.join('%s' for _ in selected)
                rows=db.execute('SELECT provider,sub_account,resource_id,billed_cost,effective_cost,list_cost,charge_category FROM focus_charges WHERE tenant_id=%s AND currency=%s AND ('+fence+') AND resource_id IN ('+marks+') AND period_start>=%s AND period_end<=%s ORDER BY id LIMIT 50001',
                    [tenant['tenant_id'],'USD',*args,*selected,begin.isoformat(),finish.isoformat()]).fetchall()
                if len(rows)>50000:raise FocusError('Narrow the resource billing charge window')
                for provider,account,rid,billed,effective,list_cost,category in rows:
                    key=(provider,rid.lower() if provider=='azure' else rid)
                    value=totals.setdefault(key,dict(billed=Decimal(0),effective=Decimal(0),list=Decimal(0),list_complete=True,locked=False,scope=account))
                    value['billed']+=Decimal(billed);value['effective']+=Decimal(effective)
                    if list_cost is None:value['list_complete']=False
                    else:value['list']+=Decimal(list_cost)
                    value['locked'] |= category=='Purchase' or Decimal(effective)>Decimal(billed)
        return {key:dict(billed_cost_usd=float(v['billed']),effective_cost_usd=float(v['effective']),list_cost_usd=float(v['list']) if v['list_complete'] else None,
            commitment_locked=v['locked'],commitment_lock_conflict=v['locked'],currency='USD',billing_coverage=all(days.get((key[0],v['scope']),{}).get((begin+timedelta(days=i)).date(),False) for i in range(window_days)),
            billing_window_start=begin.isoformat(),billing_window_end=finish.isoformat(),billing_basis='imported_FOCUS_not_provider_reconciled') for key,v in totals.items()}

    def attach(self, tenant, scan):
        from copy import deepcopy
        result=deepcopy(scan)
        rows=[*result.get('inventory',[]),*result.get('findings',[])]
        stamp=utc(scan['timestamp'])
        costs=self.resource_costs(tenant,[r['resource_id'] for r in rows],as_of=stamp)
        inventory={(r.get('cloud_provider','azure'),r['resource_id'].lower() if r.get('cloud_provider','azure')=='azure' else r['resource_id']):r for r in result.get('inventory',[])}
        for r in rows:
            key=(r.get('cloud_provider','azure'),r['resource_id'].lower() if r.get('cloud_provider','azure')=='azure' else r['resource_id'])
            # Findings inherit observed inventory evidence before billing is attached.
            e=dict((inventory.get(key) or {}).get('evidence') or {},**(r.get('evidence') or {}))
            e.update(costs.get(key,{}));r['evidence']=e
        from app.k8s_cost_reconciler import attach_node_costs
        attach_node_costs(result.get('inventory',[]))
        return result

    def imports(self,tenant,limit=25):
        with self.store.transaction(tenant['tenant_id']) as db:
            rows=db.execute('SELECT id,source_id,provider,sub_account,currency,period_start,period_end,complete,records,inserted,created_at FROM focus_imports WHERE tenant_id=%s ORDER BY created_at DESC,id DESC LIMIT %s',(tenant['tenant_id'],limit)).fetchall()
        keys='id,source_id,provider,sub_account,currency,period_start,period_end,complete,records,inserted,created_at'.split(',')
        return [dict(zip(keys,[str(r[0]),*r[1:]])) for r in rows if authorized(r[2],r[3],tenant)]

    def summary(self,tenant,start,end,currency,budget=None):
        # Keep all permitted totals, ratios and projections inside a request-local precision budget.
        with localcontext() as context:
            context.prec=60
            return self._summary(tenant,start,end,currency,budget)

    def _summary(self,tenant,start,end,currency,budget=None):
        begin=datetime.combine(start,time.min,tzinfo=timezone.utc);finish=datetime.combine(end,time.min,tzinfo=timezone.utc)
        with self.store.transaction(tenant['tenant_id']) as db:
            rows=db.execute('''SELECT provider,sub_account,period_start,period_end,billed_cost,effective_cost,list_cost,charge_category
                FROM focus_charges WHERE tenant_id=%s AND currency=%s AND period_start<%s AND period_end>%s
                ORDER BY period_start,id LIMIT 50001''',(tenant['tenant_id'],currency,finish.isoformat(),begin.isoformat())).fetchall()
            coverage=db.execute('SELECT provider,sub_account,period_start,period_end,complete FROM focus_imports WHERE tenant_id=%s AND currency=%s AND period_start<%s AND period_end>%s ORDER BY created_at,id LIMIT 50001',
                (tenant['tenant_id'],currency,end.isoformat(),start.isoformat())).fetchall()
        if len(coverage)>50000: raise FocusError('Billing coverage exceeds 50000 imports; narrow the period')
        if len(rows)>50000: raise FocusError('Billing window exceeds 50000 records; narrow the period')
        scopes={(r[0],r[1]) for r in rows if authorized(r[0],r[1],tenant)}
        scopes.update((r[0],r[1]) for r in coverage if authorized(r[0],r[1],tenant) and str(r[2])<end.isoformat() and str(r[3])>start.isoformat())
        total={k:Decimal(0) for k in ('billed','effective','list')};known_list=0;count=0;excluded=0
        daily={};providers={};nondaily=set()
        for provider,account,a,b,billed,effective,list_cost,charge_category in rows:
            if not authorized(provider,account,tenant): continue
            a,b=utc(a),utc(b)
            if a<begin or b>finish:
                excluded+=1
                day=max(a.date(),start)
                stop=min((b-timedelta(microseconds=1)).date()+timedelta(days=1),end)
                while day<stop: nondaily.add(day);day+=timedelta(days=1)
                continue
            values=(Decimal(billed),Decimal(effective),Decimal(list_cost) if list_cost is not None else None)
            count+=1;total['billed']+=values[0];total['effective']+=values[1]
            if values[2] is not None: total['list']+=values[2];known_list+=1
            group=providers.setdefault(provider,dict(records=0,billed=Decimal(0),effective=Decimal(0)))
            group['records']+=1;group['billed']+=values[0];group['effective']+=values[1]
            if (b-a).total_seconds()<=86400 and a.date()==(b-timedelta(microseconds=1)).date():
                daily[a.date()]=daily.get(a.date(),Decimal(0))+values[0]
            else:
                day=max(a.date(),start)
                while day<min((b-timedelta(microseconds=1)).date()+timedelta(days=1),end): nondaily.add(day);day+=timedelta(days=1)
        coverage_days={scope:{} for scope in scopes}
        for provider,account,a,b,complete in coverage:
            if (provider,account) not in scopes: continue
            day=max(date.fromisoformat(str(a)),start);stop=min(date.fromisoformat(str(b)),end)
            while day<stop: coverage_days[(provider,account)][day]=bool(complete);day+=timedelta(days=1)
        points=[];day=start;today=datetime.now(timezone.utc).date()
        while day<end:
            complete=bool(scopes) and all(days.get(day,False) for days in coverage_days.values()) and day not in nondaily and day<today
            value=daily.get(day,Decimal(0)) if complete else None
            points.append(dict(date=day.isoformat(),billed_cost=format(value,'f') if value is not None else None,complete=complete))
            day+=timedelta(days=1)
        # Only a complete last seven UTC days supports a provisional velocity forecast.
        closed=[p for p in points if date.fromisoformat(p['date'])<today]
        recent=closed[-7:];forecast=None;zscore=None
        if len(recent)==7 and all(p['complete'] for p in recent):
            velocity=sum(Decimal(p['billed_cost']) for p in recent)/7
            last=date.fromisoformat(recent[-1]['date'])
            month_end=(last.replace(day=28)+timedelta(days=4)).replace(day=1)
            # Forecast only from month start and a window ending at the last closed day.
            if velocity>=0 and start.day==1 and start.year==last.year and start.month==last.month and end==last+timedelta(days=1) and all(p['complete'] for p in closed):
                projected=total['billed']+velocity*(month_end-end).days
                forecast=dict(status='provisional',daily_velocity=format(velocity.quantize(Decimal('0.00000001')),'f'),
                    month_end_billed_cost=format(projected.quantize(Decimal('0.00000001')),'f'),budget=budget,
                    projected_budget_overrun=bool(budget is not None and projected>Decimal(budget)))
        if len(closed)>=31 and all(p['complete'] for p in closed[-31:]):
            baseline=[float(Decimal(p['billed_cost'])) for p in closed[-31:-1]]
            mean=sum(baseline)/30;variance=sum((x-mean)**2 for x in baseline)/30
            if variance>0:
                score=(float(Decimal(closed[-1]['billed_cost']))-mean)/math.sqrt(variance)
                zscore=dict(value=round(score,4),spike=score>=3,baseline_days=30,method='population_zscore_nonseasonal')
        esr=None
        if count and known_list==count and total['list']>0:
            esr=format(((1-total['effective']/total['list'])*100).quantize(Decimal('0.0001')),'f')
        known_total=bool(count) or bool(points) and all(p['complete'] for p in points)
        return dict(currency=currency,period_start=start,period_end=end,records=count,excluded_overlapping_records=excluded,
            billed_cost=format(total['billed'],'f') if known_total else None,effective_cost=format(total['effective'],'f') if known_total else None,
            list_cost=format(total['list'],'f') if count and known_list==count else None,effective_savings_rate_pct=esr,
            providers=[dict(provider=k,records=v['records'],billed_cost=format(v['billed'],'f'),effective_cost=format(v['effective'],'f')) for k,v in sorted(providers.items())],
            daily=points,forecast=forecast,anomaly=zscore,coverage='operator_declared_imports',billing_reconciled=False,
            realized_savings=None,warning='Imported billing evidence is not provider-reconciled. Forecasts are provisional; missing coverage remains unknown.')
