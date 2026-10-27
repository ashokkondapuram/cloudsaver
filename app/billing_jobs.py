"""Durable, tenant-owned billing queue. Providers are read only in the worker."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from app.enterprise_store import decode
from app.v150_store import WorkflowConflict

TERMINAL={'completed','failed','partial','cancelled','expired'}


class BillingJobs:
    def __init__(self,store):self.store=store

    @staticmethod
    def public(row):
        if not row:return None
        return dict(id=str(row[0]),status=row[1],payload=decode(row[2]),created_at=str(row[3]),updated_at=str(row[4]),
                    poll_url='/api/v1/finops/sync-jobs/'+str(row[0]))

    def get(self,tenant_id,id):
        with self.store.transaction(tenant_id) as db:
            return self.public(db.execute('SELECT id,state,payload,created_at,updated_at FROM billing_sync_jobs WHERE tenant_id=%s AND id=%s',(tenant_id,id)).fetchone())

    def submit(self,tenant,key,currency='USD'):
        from app.collectors.billing_sync import bindings
        import os
        from app.focus import FocusError
        if os.getenv('CLOUDSAVER_AUTO_BILLING_SYNC','true')!='true':raise FocusError('Automatic billing sync is disabled',503)
        selected=bindings(tenant)
        if not selected:raise FocusError('No authorized cloud billing connector is configured',503)
        if len(selected)>8:raise FocusError('A billing job supports at most eight authorized scopes',422)
        tid=tenant['tenant_id'];now=datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tid,write=True) as db:
            if db.postgres:db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('billing-submit:'+tid,))
            prior=db.execute('SELECT id,payload FROM billing_sync_jobs WHERE tenant_id=%s AND request_key=%s',(tid,key)).fetchone()
            if prior:
                if decode(prior[1])['currency']!=currency:raise WorkflowConflict('This request key belongs to a different currency')
                id=str(prior[0])
            else:
                active=db.execute("SELECT id,payload FROM billing_sync_jobs WHERE tenant_id=%s AND state IN ('queued','running','cancel_requested') ORDER BY created_at LIMIT 1",(tid,)).fetchone()
                if active:
                    raise WorkflowConflict('Another billing synchronization is active; inspect sync status before submitting a new request')
                else:
                    id=str(uuid4());end=datetime.now(timezone.utc).date()-timedelta(days=2)
                    payload=dict(currency=currency,bindings=selected,scope_index=0,scope_results=[],period_start=str(end-timedelta(days=30)),period_end=str(end),coverage_verified=False)
                    db.execute("INSERT INTO billing_sync_jobs(id,tenant_id,request_key,state,payload,created_at,updated_at) VALUES(%s,%s,%s,'queued',%s,%s,%s)",(id,tid,key,db.json(payload),now,now))
        return self.get(tid,id)

    def cancel(self,tenant_id,id):
        with self.store.transaction(tenant_id,write=True) as db:
            db.execute("UPDATE billing_sync_jobs SET state=CASE WHEN state='queued' THEN 'cancelled' ELSE 'cancel_requested' END,updated_at=%s WHERE tenant_id=%s AND id=%s AND state IN ('queued','running')",(datetime.now(timezone.utc).isoformat(),tenant_id,id))
        return self.get(tenant_id,id)

    def claim(self,tenant_id,*,now=None):
        now=now or datetime.now(timezone.utc)
        with self.store.transaction(tenant_id,write=True) as db:
            if db.postgres:db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('billing-submit:'+tenant_id,))
            suffix=' FOR UPDATE SKIP LOCKED' if db.postgres else ''
            row=db.execute("SELECT id,payload,created_at,state FROM billing_sync_jobs WHERE tenant_id=%s AND (state='queued' OR (state IN ('running','cancel_requested') AND lease_until<%s)) ORDER BY created_at LIMIT 1"+suffix,(tenant_id,now.isoformat())).fetchone()
            if not row:return None
            if row[3]=='cancel_requested' or datetime.fromisoformat(str(row[2]).replace('Z','+00:00'))<now-timedelta(hours=6):
                state='cancelled' if row[3]=='cancel_requested' else 'expired'
                db.execute('UPDATE billing_sync_jobs SET state=%s,updated_at=%s WHERE tenant_id=%s AND id=%s',(state,now.isoformat(),tenant_id,row[0]));return None
            token=str(uuid4())
            db.execute("UPDATE billing_sync_jobs SET state='running',lease_token=%s,lease_until=%s,updated_at=%s WHERE tenant_id=%s AND id=%s",(token,(now+timedelta(minutes=30)).isoformat(),now.isoformat(),tenant_id,row[0]))
            return dict(id=str(row[0]),token=token,payload=decode(row[1]))

    def execute_scope(self,tenant,claim,*,readers=None,refresh=None,commitment_readers=None):
        """Read outside DB locks, then fence commits. Replay after a crash is a read plus exact delta deduplication.

        Injected billing readers without commitment readers skip commitment collection."""
        from app.collectors.billing_sync import MAX_ROWS,READERS,bindings,_import_snapshot
        from app.collectors import commitments as commitment_reader
        from app import commitment_store
        from app.focus import FocusRepository
        from datetime import date
        import re,os
        tid=tenant['tenant_id'];p=claim['payload'];binding=p['bindings'][p['scope_index']]
        try:
            if binding not in bindings(tenant) or os.getenv('CLOUDSAVER_AUTO_BILLING_SYNC','true')!='true' or (tenant.get('plan') or {}).get('access_suspended'):
                raise ValueError('Billing grant was revoked')
            rows,grain,warnings=(readers or READERS)[binding['provider']](binding,tenant,date.fromisoformat(p['period_start']),date.fromisoformat(p['period_end']))
            if len(rows)>MAX_ROWS:raise ValueError('Bounded result limit exceeded')
            result=dict(provider=binding['provider'],scope_id=binding['scope_id'],status='completed',granularity=grain,warnings=warnings,coverage_verified=False)
        except Exception:
            rows=None;result=dict(provider=binding['provider'],scope_id=binding['scope_id'],status='failed',error_code='BILLING_SOURCE_UNAVAILABLE_OR_INVALID',correlation_id=claim['id'])
        snapshot=None
        selected=commitment_readers if commitment_readers is not None else (None if readers else commitment_reader.READERS)
        if selected and binding['provider'] in selected and os.getenv('CLOUDSAVER_COMMITMENT_SYNC','true')=='true':
            try:
                items,coverage,notes=selected[binding['provider']](binding,tenant,date.fromisoformat(p['period_start']),date.fromisoformat(p['period_end']))
                snapshot=('completed',dict(items=items,coverage=coverage or {},warnings=notes,summary=commitment_reader.summarize(items),
                                           period_start=p['period_start'],period_end=p['period_end']))
            except Exception:
                # Provider exceptions can include credentials, resource IDs and response bodies.
                snapshot=('failed',dict(items=[],coverage={},warnings=[],error_code='COMMITMENT_SOURCE_UNAVAILABLE_OR_INVALID',
                                        period_start=p['period_start'],period_end=p['period_end']))
            result['commitments']=dict(status=snapshot[0],count=len(snapshot[1]['items']))
        with self.store.transaction(tid,write=True) as db:
            suffix=' FOR UPDATE' if db.postgres else ''
            current=db.execute('SELECT state,lease_token,lease_until FROM billing_sync_jobs WHERE tenant_id=%s AND id=%s'+suffix,(tid,claim['id'])).fetchone()
            if not current or str(current[1])!=claim['token'] or datetime.fromisoformat(str(current[2]).replace('Z','+00:00'))<=datetime.now(timezone.utc):raise WorkflowConflict('Billing lease was lost; no charge commit is permitted')
            if current[0]=='cancel_requested':
                db.execute("UPDATE billing_sync_jobs SET state='cancelled',updated_at=%s WHERE tenant_id=%s AND id=%s",(datetime.now(timezone.utc).isoformat(),tid,claim['id']));return
            if rows is not None or snapshot is not None:
                live=refresh() if refresh else tenant
                if not live or not live.get('active',True) or binding not in bindings(live) or (live.get('plan') or {}).get('access_suspended'):
                    rows=None;snapshot=None;result.update(status='failed',error_code='BILLING_SCOPE_REVOKED',correlation_id=claim['id'])
            if snapshot is not None:
                commitment_store.record(db,tid,binding['provider'],binding['scope_id'],claim['id'],*snapshot)
            if rows is not None:
                db.execute('SAVEPOINT billing_import')
                try:
                    currencies=sorted({r['currency'] for r in rows}) if p['currency'] is None else [p['currency']]
                    if p['currency'] is None:
                        prior=db.execute('SELECT DISTINCT currency FROM focus_charges WHERE tenant_id=%s AND provider=%s AND sub_account=%s AND charge_id LIKE %s AND period_start>=%s AND period_start<%s LIMIT 17',(tid,binding['provider'],binding['scope_id'],'auto:%',p['period_start'],p['period_end'])).fetchall()
                        currencies=sorted(set(currencies)|{r[0] for r in prior})
                        if len(currencies)>16:raise ValueError('Currency bound exceeded')
                    if any(not re.fullmatch('[A-Z]{3}',c) for c in currencies) or rows and p['currency'] and not any(r['currency']==p['currency'] for r in rows):raise ValueError('Requested currency unavailable')
                    imports=[_import_snapshot(FocusRepository(self.store),tenant,binding,rows,date.fromisoformat(p['period_start']),date.fromisoformat(p['period_end']),c,_db=db) for c in currencies]
                    db.execute('RELEASE SAVEPOINT billing_import')
                    result.update(inserted=sum(r['inserted'] for r in imports),unresolved_absent_groups=sum(r.get('unresolved_absent_groups',0) for r in imports),reconciliation_status='unverified')
                except Exception:
                    db.execute('ROLLBACK TO SAVEPOINT billing_import')
                    db.execute('RELEASE SAVEPOINT billing_import')
                    result.update(status='failed',error_code='BILLING_IMPORT_UNCERTAIN_OR_INVALID',correlation_id=claim['id'])
            p['scope_results'].append(result);p['scope_index']+=1
            if p['scope_index']<len(p['bindings']):state='queued'
            else:state='completed' if all(r['status']=='completed' for r in p['scope_results']) else 'partial' if any(r['status']=='completed' for r in p['scope_results']) else 'failed'
            db.execute('UPDATE billing_sync_jobs SET state=%s,payload=%s,updated_at=%s,lease_until=NULL,lease_token=NULL WHERE tenant_id=%s AND id=%s',(state,db.json(p),datetime.now(timezone.utc).isoformat(),tid,claim['id']))
