"""Atomic, versioned savings case lifecycle and append-only collector evidence."""
from datetime import datetime,timezone
from uuid import uuid4
import hashlib,json
from app.enterprise_store import decode
from app.realized_savings_verifier import TRANSITIONS,evaluate_realized_savings
from app.telemetry_contract import moment

COLUMNS='id,provider,scope_id,resource_id,baseline_scan_id,state,version,payload,verification,created_at,updated_at'


class SavingsConflict(ValueError):pass


def actor(tenant):
    return hashlib.sha256((tenant.get('subject_id') or tenant.get('user_id') or tenant.get('key_id') or tenant['tenant_id']).encode()).hexdigest()


def visible(case,tenant):
    from app.focus import authorized
    from app.provider_access import finding_in_scope
    if tenant.get('allowed_providers') is not None and case['provider'] not in tenant['allowed_providers']:return False
    limits=tenant.get('scope_restrictions')
    return finding_in_scope({'cloud_provider':case['provider'],'scope_id':case['scope_id'],'subscription_id':case['scope_id']},limits)


class SavingsRepository:
    def __init__(self,store):self.store=store

    def _view(self,row):
        if row is None:return None
        result=dict(zip(COLUMNS.split(','),row))
        for key in ('id','baseline_scan_id','created_at','updated_at'):result[key]=str(result[key])
        result['payload']=decode(result['payload']);result['verification']=decode(result['verification']) if result['verification'] is not None else None
        return result

    def _get(self,db,tenant_id,case_id):
        return self._view(db.execute(f'SELECT {COLUMNS} FROM savings_cases WHERE tenant_id=%s AND id=%s',(tenant_id,case_id)).fetchone())

    def _event(self,db,tenant_id,case,action,payload,actor_id):
        db.execute('INSERT INTO savings_case_events(id,tenant_id,case_id,action,version,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (str(uuid4()),tenant_id,case['id'],action,case['version'],db.json(payload),actor_id,datetime.now(timezone.utc).isoformat()))

    def create(self,tenant,snapshot,resource,request_key,action,note):
        fingerprint=hashlib.sha256(json.dumps([snapshot['scan_id'],resource['resource_id'],action,note],separators=(',',':')).encode()).hexdigest()
        now=datetime.now(timezone.utc).isoformat();tid=tenant['tenant_id']
        with self.store.transaction(tid,write=True) as db:
            previous=db.execute('SELECT id,fingerprint FROM savings_cases WHERE tenant_id=%s AND request_key=%s',(tid,request_key)).fetchone()
            if previous:
                if previous[1]!=fingerprint:raise SavingsConflict('Idempotency key belongs to a different case request.')
                return self._get(db,tid,str(previous[0]))
            if db.execute('SELECT count(*) FROM savings_cases WHERE tenant_id=%s',(tid,)).fetchone()[0]>=1000:raise SavingsConflict('Workspace savings case limit reached.')
            case_id=str(uuid4());payload={'action':action,'note':note,'resource_name':resource.get('resource_name'),
                'resource_type':resource['resource_type'],'region':resource.get('region'),'baseline_observed_at':snapshot['timestamp'],'scheduled_at':None,
                'baseline_rule_ids':sorted({r['rule_id'] for r in snapshot.get('findings',[]) if r['resource_id']==resource['resource_id']})}
            db.execute('''INSERT INTO savings_cases(id,tenant_id,provider,scope_id,resource_id,baseline_scan_id,request_key,fingerprint,state,version,payload,actor,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'reviewed',1,%s,%s,%s,%s)''',
                (case_id,tid,resource.get('cloud_provider','azure'),resource.get('scope_id') or resource['subscription_id'],resource['resource_id'],snapshot['scan_id'],request_key,fingerprint,db.json(payload),actor(tenant),now,now))
            case=self._get(db,tid,case_id);self._event(db,tid,case,'case_created',{'state':'reviewed'},actor(tenant));return case

    def list(self,tenant):
        with self.store.transaction(tenant['tenant_id']) as db:
            rows=db.execute(f'SELECT {COLUMNS} FROM savings_cases WHERE tenant_id=%s ORDER BY updated_at DESC,id DESC LIMIT 1001',(tenant['tenant_id'],)).fetchall()
        return [case for row in rows if visible(case:=self._view(row),tenant)]

    def get(self,tenant,case_id):
        with self.store.transaction(tenant['tenant_id']) as db:
            case=self._get(db,tenant['tenant_id'],case_id)
            if not case or not visible(case,tenant):return None
            rows=db.execute('SELECT action,version,payload,actor,created_at FROM savings_case_events WHERE tenant_id=%s AND case_id=%s ORDER BY version',(tenant['tenant_id'],case_id)).fetchall()
            case['events']=[{'action':r[0],'version':r[1],'payload':decode(r[2]),'actor':r[3],'created_at':str(r[4])} for r in rows]
            return case

    def transition(self,tenant,case_id,version,state,note):
        tid=tenant['tenant_id']
        with self.store.transaction(tid,write=True) as db:
            case=self._get(db,tid,case_id)
            if not case or not visible(case,tenant):return None
            if case['version']!=version:raise SavingsConflict('Case changed. Refresh before updating.')
            if state not in TRANSITIONS[case['state']]:raise SavingsConflict('This transition requires a different review state or trusted verification.')
            payload=dict(case['payload'],note=note)
            if state=='scheduled':payload['scheduled_at']=datetime.now(timezone.utc).isoformat()
            db.execute('UPDATE savings_cases SET state=%s,version=version+1,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=%s',
                (state,db.json(payload),datetime.now(timezone.utc).isoformat(),tid,case_id,version))
            updated=self._get(db,tid,case_id);self._event(db,tid,updated,'review_transition',{'before':case['state'],'after':state},actor(tenant));return updated

    def save_receipt(self,tenant,receipt,payload,fingerprint):
        tid=tenant['tenant_id'];rid=receipt.resource_id.lower() if receipt.provider=='azure' else receipt.resource_id
        with self.store.transaction(tid,write=True) as db:
            cases=db.execute('SELECT provider,scope_id,resource_id FROM savings_cases WHERE tenant_id=%s AND provider=%s AND scope_id=%s',(tid,receipt.provider,receipt.scope_id)).fetchall()
            if not any((r[2].lower() if receipt.provider=='azure' else r[2])==rid for r in cases):raise SavingsConflict('Register an owned savings case before submitting collector evidence.')
            previous=db.execute('SELECT id,fingerprint FROM savings_evidence_receipts WHERE tenant_id=%s AND source_id=%s AND receipt_key=%s',(tid,receipt.source_id,receipt.receipt_id)).fetchone()
            if previous:
                if previous[1]!=fingerprint:raise SavingsConflict('Receipt identity has conflicting evidence.')
                return dict(id=str(previous[0]),cached=True)
            identifier=str(uuid4())
            db.execute('''INSERT INTO savings_evidence_receipts(id,tenant_id,receipt_key,source_id,provider,scope_id,resource_id,kind,fingerprint,payload,issued_at,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (identifier,tid,receipt.receipt_id,receipt.source_id,receipt.provider,receipt.scope_id,rid,receipt.kind,fingerprint,db.json(payload),receipt.issued_at,datetime.now(timezone.utc).isoformat()))
            return dict(id=identifier,cached=False)

    def _receipt(self,db,tid,case,kind):
        rid=case['resource_id'].lower() if case['provider']=='azure' else case['resource_id']
        row=db.execute('''SELECT id,source_id,payload,issued_at FROM savings_evidence_receipts
            WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND resource_id=%s AND kind=%s ORDER BY issued_at DESC,id DESC LIMIT 1''',
            (tid,case['provider'],case['scope_id'],rid,kind)).fetchone()
        if not row:return None
        from app.nextgen_evidence import current_sources
        try:
            sources=current_sources()
        except (ValueError,TypeError):return None
        if not any(s['tenant_id']==tid and s['source_id']==row[1] and kind in s['kinds'] and case['provider'] in s['providers'] and case['scope_id'] in s['scope_ids'] for s in sources):return None
        return dict(decode(row[2]),trusted=True,receipt_id=str(row[0]),source_id=row[1],issued_at=str(row[3]))

    def slo_gate(self,tenant,resource):
        with self.store.transaction(tenant['tenant_id']) as db:
            value=self._receipt(db,tenant['tenant_id'],dict(provider=resource.get('cloud_provider','azure'),scope_id=resource.get('scope_id') or resource.get('subscription_id'),resource_id=resource['resource_id']),'slo')
        now=datetime.now(timezone.utc);stamp=moment((value or {}).get('observed_at'));issued=moment((value or {}).get('issued_at'))
        window_end=moment(((value or {}).get('gate') or {}).get('observation_window_end'))
        if not stamp or not issued or not window_end or not all(0<=(now-point).total_seconds()<86400 for point in (stamp,issued,window_end)):return None
        return value['gate']

    def verify(self,tenant,case_id,scan,version=None,*,system=False):
        tid=tenant['tenant_id']
        with self.store.transaction(tid,write=True) as db:
            case=self._get(db,tid,case_id)
            if not case or not visible(case,tenant):return None
            if version is not None and case['version']!=version:raise SavingsConflict('Case changed. Refresh before verification.')
            previous=(case['payload'].get('last_verified_result') or case.get('verification') or {})
            args=dict(case,**case['payload'],previous_verified_savings=previous.get('verified_realized_savings_usd'))
            proofs={kind:self._receipt(db,tid,case,kind) for kind in ('audit','billing','slo')}
            result=evaluate_realized_savings(args,scan,**proofs)
            result['evidence_receipts']={kind:value['receipt_id'] for kind,value in proofs.items() if value}
            if system and result['state']==case['state']:return case
            if not system and case.get('verification')==result:return case
            if result['status']=='verified_by_trusted_receipts':
                event=proofs['audit']
                rid=case['resource_id'].lower() if case['provider']=='azure' else case['resource_id']
                event_key=hashlib.sha256(json.dumps([case['provider'],case['scope_id'],rid,event['event_id']],separators=(',',':')).encode()).hexdigest()
                claimed=db.execute('SELECT case_id FROM savings_verified_actions WHERE tenant_id=%s AND event_key=%s',(tid,event_key)).fetchone()
                if claimed and str(claimed[0])!=case_id:raise SavingsConflict('This provider action has already been credited to another savings case.')
                if not claimed:
                    db.execute('INSERT INTO savings_verified_actions(id,tenant_id,case_id,event_key,receipt_id,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
                        (str(uuid4()),tid,case_id,event_key,event['receipt_id'],datetime.now(timezone.utc).isoformat()))
            payload=dict(case['payload'])
            if result['status']=='verified_by_trusted_receipts':payload['last_verified_result']=result
            db.execute('UPDATE savings_cases SET state=%s,version=version+1,verification=%s,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=%s',
                (result['state'],db.json(result),db.json(payload),datetime.now(timezone.utc).isoformat(),tid,case_id,case['version']))
            updated=self._get(db,tid,case_id)
            self._event(db,tid,updated,'regression_reopened' if result['state']=='reopened_on_regression' else 'verification_evaluated',dict(result,scan_id=scan['scan_id']),actor(tenant))
            return updated

    def reconcile_regressions(self,tenant,scan):
        count=0
        for case in self.list(tenant):
            if case['state']=='verified_completed':
                result=self.verify(tenant,case['id'],scan,system=True)
                count+=bool(result and result['state']=='reopened_on_regression')
        return count
