"""Erase model content while retaining usage, idempotency fences and audit evidence."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import re
from app.enterprise_store import decode
from app.savings_store import actor


class RetentionConflict(ValueError):pass


class DataRetention:
    def __init__(self,store,clock=None):self.store=store;self.clock=clock or (lambda:datetime.now(timezone.utc))

    def _erase(self,db,tid,attempt_id,actor_id,reference=None):
        source=db.execute('SELECT request_key FROM ai_inference_attempts WHERE tenant_id=%s AND id=%s',(tid,attempt_id)).fetchone()
        if db.postgres:
            changed=db.execute('SELECT erase_ai_content(%s,%s,%s)',(attempt_id,actor_id,reference)).fetchone()[0]
            if changed and source:self._erase_agent_by_key(db,tid,str(source[0]),actor_id)
            return changed
        row=db.execute('SELECT purpose,policy_digest,expires_at,erased_at FROM ai_data_retention WHERE tenant_id=%s AND attempt_id=%s',(tid,attempt_id)).fetchone()
        if not row or row[3] or (reference is None and datetime.fromisoformat(row[2].replace('Z','+00:00'))>self.clock()):return False
        if db.execute("SELECT 1 FROM ai_inference_attempts WHERE tenant_id=%s AND id=%s AND status='pending'",(tid,attempt_id)).fetchone():return False
        if db.execute('SELECT 1 FROM ai_data_holds WHERE tenant_id=%s AND attempt_id=%s AND hold_until>%s',(tid,attempt_id,self.clock().isoformat())).fetchone():return False
        db.execute('INSERT INTO _ai_erasure_permits(attempt_id,tenant_id) VALUES(%s,%s)',(attempt_id,tid))
        db.execute('UPDATE ai_inference_attempts SET response=NULL,content_erased_at=%s WHERE tenant_id=%s AND id=%s',(self.clock().isoformat(),tid,attempt_id))
        db.execute('DELETE FROM _ai_erasure_permits WHERE tenant_id=%s AND attempt_id=%s',(tid,attempt_id))
        db.execute("UPDATE ai_followups SET question='[ERASED BY DATA RETENTION]' WHERE tenant_id=%s AND attempt_id=%s",(tid,attempt_id))
        db.execute('UPDATE ai_data_retention SET erased_at=%s WHERE tenant_id=%s AND attempt_id=%s',(self.clock().isoformat(),tid,attempt_id))
        db.execute('INSERT INTO ai_data_events(id,tenant_id,purpose,decision,reason,policy_digest,target_id,metadata,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (str(uuid4()),tid,row[0],'erased','PRIVACY_REQUEST' if reference else 'RETENTION_EXPIRED',row[1],None,db.json({'review_reference':reference}),actor_id,self.clock().isoformat()))
        if source:self._erase_agent_by_key(db,tid,str(source[0]),actor_id)
        return True

    def _erase_agent(self,db,tid,task_id,actor_id):
        from app.agent_store import AgentRepository,TERMINAL
        repository=AgentRepository(self.store,self.clock);task=repository._row(db,tid,task_id)
        if not task or task['payload'].get('data_erased'):return False
        payload=task['payload'];inflight=any(s.get('state')=='started' for s in payload.get('steps',[]))
        state='needs_reconciliation' if inflight else task['state'] if task['state'] in TERMINAL else 'cancelled'
        payload.update(intent='[ERASED BY DATA GOVERNANCE]',plan=None,steps=[],connector_bindings=[],approval=None,data_erased=True)
        payload.pop('lease',None)
        repository._save(db,task,state,'ai_content_erased',actor_id,dict(content_erased=True,automatic_retry=False))
        db.execute('INSERT INTO ai_data_events(id,tenant_id,purpose,decision,reason,policy_digest,target_id,metadata,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (str(uuid4()),tid,'agent_planning','erased','TASK_CONTENT_ERASED','0'*64,payload.get('target_id'),db.json({'task_reference':task_id}),actor_id,self.clock().isoformat()))
        return True

    def _erase_agent_by_key(self,db,tid,key,actor_id):
        row=db.execute("SELECT id FROM agent_tasks WHERE tenant_id=%s AND payload->>'draft_key'=%s",(tid,key)).fetchone()
        if row:self._erase_agent(db,tid,str(row[0]),actor_id)

    def purge(self,tenant_id,limit=200):
        if not 1<=limit<=1000:raise ValueError('Invalid purge bound')
        with self.store.transaction(tenant_id,write=True) as db:
            now=self.clock().isoformat()
            rows=db.execute('''SELECT r.attempt_id FROM ai_data_retention r JOIN ai_inference_attempts a ON a.id=r.attempt_id AND a.tenant_id=r.tenant_id
                WHERE r.tenant_id=%s AND r.erased_at IS NULL AND r.expires_at<=%s AND a.status<>'pending'
                AND NOT EXISTS(SELECT 1 FROM ai_data_holds h WHERE h.tenant_id=r.tenant_id AND h.attempt_id=r.attempt_id AND h.hold_until>%s)
                ORDER BY r.expires_at,r.attempt_id LIMIT %s''',(tenant_id,now,now,limit)).fetchall()
            count=sum(bool(self._erase(db,tenant_id,str(row[0]),'0'*64)) for row in rows)
            tasks=db.execute('''SELECT t.id FROM agent_tasks t WHERE t.tenant_id=%s AND t.payload->>'data_erased' IS NULL
                AND ((t.payload->>'data_retention_expires_at' IS NOT NULL AND t.payload->>'data_retention_expires_at'<=%s)
                    OR (t.payload->>'data_retention_expires_at' IS NULL AND t.created_at<=%s))
                AND NOT EXISTS(SELECT 1 FROM ai_inference_attempts a JOIN ai_data_holds h ON h.tenant_id=a.tenant_id AND h.attempt_id=a.id
                    WHERE a.tenant_id=t.tenant_id AND CAST(a.request_key AS TEXT)=t.payload->>'draft_key' AND h.hold_until>%s)
                ORDER BY t.created_at LIMIT %s''',(tenant_id,now,(self.clock()-timedelta(days=7)).isoformat(),now,limit)).fetchall()
            return count+sum(bool(self._erase_agent(db,tenant_id,str(row[0]),'0'*64)) for row in tasks)

    def erase(self,tenant,attempt_id,reference):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{2,119}',reference):raise RetentionConflict('Use an internal privacy-request reference.')
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            if not self._erase(db,tenant['tenant_id'],attempt_id,actor(tenant),reference):
                raise RetentionConflict('Content is missing, already erased, still processing, or subject to an active legal hold.')
        return dict(attempt_id=attempt_id,content_erased=True,usage_and_request_fence_retained=True)

    def hold(self,tenant,attempt_id,hold_until,reference):
        if not self.clock()<hold_until<=self.clock()+timedelta(days=30):raise RetentionConflict('Legal holds must expire within 30 days.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{2,119}',reference):raise RetentionConflict('Use an internal legal-review reference.')
        tid=tenant['tenant_id'];now=self.clock().isoformat();identifier=str(uuid4())
        with self.store.transaction(tid,write=True) as db:
            # Lock the attempt, on which runtime has outcome-update privileges;
            # retention metadata itself deliberately has no runtime UPDATE grant.
            if db.postgres:
                db.execute('SELECT id FROM ai_inference_attempts WHERE tenant_id=%s AND id=%s FOR UPDATE',(tid,attempt_id)).fetchone()
            record=db.execute('SELECT erased_at,purpose,policy_digest FROM ai_data_retention WHERE tenant_id=%s AND attempt_id=%s',(tid,attempt_id)).fetchone()
            if not record or record[0]:raise RetentionConflict('Content is missing or already erased; a hold cannot restore it.')
            db.execute('INSERT INTO ai_data_holds(id,tenant_id,attempt_id,review_reference,hold_until,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (identifier,tid,attempt_id,reference,hold_until.isoformat(),actor(tenant),now))
            db.execute('INSERT INTO ai_data_events(id,tenant_id,purpose,decision,reason,policy_digest,target_id,metadata,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (str(uuid4()),tid,record[1],'held','TIME_BOUND_LEGAL_HOLD',record[2],None,db.json({'review_reference':reference,'hold_until':hold_until.isoformat()}),actor(tenant),now))
        return dict(id=identifier,attempt_id=attempt_id,hold_until=hold_until.isoformat())

    def view(self,tenant):
        tid=tenant['tenant_id']
        with self.store.transaction(tid) as db:
            events=db.execute('SELECT id,purpose,decision,reason,target_id,metadata,created_at,actor FROM ai_data_events WHERE tenant_id=%s ORDER BY created_at DESC,id DESC LIMIT 100',(tid,)).fetchall()
            records=db.execute('SELECT attempt_id,purpose,expires_at,erased_at FROM ai_data_retention WHERE tenant_id=%s ORDER BY created_at DESC,attempt_id DESC LIMIT 100',(tid,)).fetchall()
            holds=db.execute('SELECT attempt_id,hold_until,review_reference FROM ai_data_holds WHERE tenant_id=%s AND hold_until>%s ORDER BY hold_until DESC LIMIT 100',(tid,self.clock().isoformat())).fetchall()
            counts=db.execute('SELECT decision,count(*) FROM ai_data_events WHERE tenant_id=%s GROUP BY decision',(tid,)).fetchall()
        return dict(events=[dict(id=str(r[0]),purpose=r[1],decision=r[2],reason=r[3],target_id=r[4],metadata=decode(r[5]),created_at=str(r[6]),actor_reference=r[7]) for r in events],
            records=[dict(attempt_id=str(r[0]),purpose=r[1],expires_at=str(r[2]),erased_at=str(r[3]) if r[3] else None) for r in records],
            active_holds=[dict(attempt_id=str(r[0]),hold_until=str(r[1]),review_reference=r[2]) for r in holds],counts=dict(counts))
