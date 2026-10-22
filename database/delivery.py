from database.connection import connect as pooled_connect
"""PostgreSQL transactional outbox. No database/network clients at import time."""
import hashlib
from contextlib import contextmanager
from uuid import UUID, uuid4, uuid5


PUBLIC_COLUMNS = 'id,kind,job_id,scan_id,target_id,status,attempts,replay_count,error_code,created_at,updated_at,next_attempt_at,lease_until'


class DeliveryConflict(ValueError):
    pass


def audit(db, tenant_id, event_id, action, actor='system'):
    db.execute('''INSERT INTO delivery_audit(id,tenant_id,event_id,action,actor,status,attempts,error_code)
        SELECT %s,tenant_id,id,%s,%s,status,attempts,error_code FROM delivery_events WHERE id=%s AND tenant_id=%s''',
        (uuid4(),action,actor,event_id,tenant_id))


def enqueue(db, tenant_id, kind, *, job_id=None, scan_id=None, target=None, payload=None):
    """Must use the caller's existing transaction: rollback includes intent + audit."""
    from psycopg.types.json import Jsonb
    identity = f'{kind}|{job_id if kind=="scan" else scan_id}|{target.target_id if target else ""}|{target.fingerprint if target else ""}'
    digest = hashlib.sha256(identity.encode()).hexdigest()
    event_id = uuid5(UUID(tenant_id),digest)
    row = db.execute('''INSERT INTO delivery_events(id,tenant_id,kind,dedupe_key,job_id,scan_id,target_id,target_fingerprint,payload)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,dedupe_key) DO NOTHING RETURNING id''',
        (event_id,tenant_id,kind,digest,job_id,scan_id,target.target_id if target else None,
         target.fingerprint if target else None,Jsonb(payload or {}))).fetchone()
    if row:
        audit(db,tenant_id,event_id,'enqueued')
    return str(event_id)


def notification_payload(scan):
    # Only aggregate counts, never resource names, IDs, costs or scan-supplied text.
    return {'findings_count':int(scan['total_items_found']), 'scopes_count':int(scan['subscriptions_scanned'])}


def refresh_notification_status(db,tenant_id,job_id):
    if job_id is None:
        return
    # Serialize the projection, then take a new READ COMMITTED statement snapshot
    # so concurrent acknowledgments from different targets cannot leave it stale.
    db.execute('SELECT 1 FROM scan_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE',(tenant_id,job_id))
    db.execute("""UPDATE scan_jobs SET notification_status=(
        SELECT CASE WHEN bool_and(status='delivered') THEN 'sent'
            WHEN bool_or(status='dead_letter') THEN 'failed' ELSE 'queued' END
        FROM delivery_events WHERE tenant_id=%s AND job_id=%s AND kind='notification'
    ) WHERE tenant_id=%s AND id=%s""",(tenant_id,job_id,tenant_id,job_id))


class DeliveryRepository:
    def __init__(self,url):
        if not url:
            raise ValueError('Durable delivery requires PostgreSQL')
        from app.store import PostgresStore
        PostgresStore(url)
        self.url = url
        with self.transaction(str(UUID(int=0))) as db:
            for table in ('delivery_events','delivery_audit','delivery_dispatchers'):
                flags = db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)',('public.'+table,)).fetchone()
                if not flags or not all(flags):
                    raise ValueError('Apply forced-RLS delivery migrations first')

    @contextmanager
    def transaction(self,tenant_id):
        import psycopg
        with pooled_connect(self.url,connect_timeout=5) as db:
            db.execute("SELECT set_config('app.current_tenant_id',%s,true)",(str(UUID(tenant_id)),))
            db.execute("SET LOCAL statement_timeout='10s'")
            yield db

    @staticmethod
    def _public(row,columns=PUBLIC_COLUMNS):
        if not row:
            return None
        return {key:(str(value) if isinstance(value,UUID) else value) for key,value in zip(columns.split(','),row)}

    def get(self,tenant_id,event_id):
        with self.transaction(tenant_id) as db:
            return self._public(db.execute(f'SELECT {PUBLIC_COLUMNS} FROM delivery_events WHERE tenant_id=%s AND id=%s',(tenant_id,event_id)).fetchone())

    def list(self,tenant_id,limit=50,status=None,before=None):
        with self.transaction(tenant_id) as db:
            if before and not db.execute('SELECT 1 FROM delivery_events WHERE tenant_id=%s AND id=%s',(tenant_id,before)).fetchone():
                raise DeliveryConflict('Invalid delivery cursor')
            return [self._public(row) for row in db.execute(f'''SELECT {PUBLIC_COLUMNS} FROM delivery_events
                WHERE tenant_id=%s AND (%s::text IS NULL OR status=%s) AND (%s::uuid IS NULL OR (created_at,id)<
                (SELECT created_at,id FROM delivery_events WHERE tenant_id=%s AND id=%s))
                ORDER BY created_at DESC,id DESC LIMIT %s''',(tenant_id,status,status,before,tenant_id,before,limit))]

    def page(self,tenant_id,limit=50,status=None,before=None):
        rows=self.list(tenant_id,limit+1,status,before)
        return {'items':rows[:limit],'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None}

    def history(self,tenant_id,event_id,limit=100,before=None):
        with self.transaction(tenant_id) as db:
            if not db.execute('SELECT 1 FROM delivery_events WHERE tenant_id=%s AND id=%s',(tenant_id,event_id)).fetchone():
                return None
            if before and not db.execute('SELECT 1 FROM delivery_audit WHERE tenant_id=%s AND event_id=%s AND id=%s',(tenant_id,event_id,before)).fetchone():
                raise DeliveryConflict('Audit cursor does not belong to this delivery')
            rows = db.execute('''SELECT id,action,actor,status,attempts,error_code,created_at FROM delivery_audit
                WHERE tenant_id=%s AND event_id=%s AND (%s::uuid IS NULL OR (created_at,id) <
                (SELECT created_at,id FROM delivery_audit WHERE tenant_id=%s AND event_id=%s AND id=%s))
                ORDER BY created_at DESC,id DESC LIMIT %s''',(tenant_id,event_id,before,tenant_id,event_id,before,limit+1)).fetchall()
            return {'items':[self._public(r,'id,action,actor,status,attempts,error_code,created_at') for r in rows[:limit]],
                    'next_cursor':str(rows[limit-1][0]) if len(rows)>limit else None}

    def summary(self,tenant_id):
        with self.transaction(tenant_id) as db:
            rows=db.execute('SELECT kind,status,count(*) FROM delivery_events WHERE tenant_id=%s GROUP BY kind,status',(tenant_id,)).fetchall()
            age=db.execute("SELECT extract(epoch FROM clock_timestamp()-min(CASE WHEN status='leased' THEN lease_until ELSE next_attempt_at END)) FROM delivery_events WHERE tenant_id=%s AND ((status IN ('pending','published') AND next_attempt_at<=clock_timestamp()) OR (status='leased' AND lease_until<=clock_timestamp()))",(tenant_id,)).fetchone()[0]
            heartbeat=db.execute('SELECT last_poll_at,last_success_at,last_error_at FROM delivery_dispatchers WHERE tenant_id=%s',(tenant_id,)).fetchone()
            return {'counts':[{'kind':k,'status':s,'count':n} for k,s,n in rows], 'oldest_due_seconds':float(age) if age is not None else None,
                    'dispatcher':self._public(heartbeat,'last_poll_at,last_success_at,last_error_at')}

    def heartbeat(self,tenant_id,success):
        with self.transaction(tenant_id) as db:
            db.execute('''INSERT INTO delivery_dispatchers(tenant_id,last_poll_at,last_success_at,last_error_at)
                SELECT tenant_id,clock_timestamp(),CASE WHEN %s THEN clock_timestamp() END,CASE WHEN NOT %s THEN clock_timestamp() END
                FROM tenants WHERE tenant_id=%s
                ON CONFLICT(tenant_id) DO UPDATE SET last_poll_at=EXCLUDED.last_poll_at,
                last_success_at=coalesce(EXCLUDED.last_success_at,delivery_dispatchers.last_success_at),
                last_error_at=coalesce(EXCLUDED.last_error_at,delivery_dispatchers.last_error_at)''',(success,success,tenant_id))

    def enqueue_notification(self,tenant_id,scan,targets):
        with self.transaction(tenant_id) as db:
            return [enqueue(db,tenant_id,'notification',scan_id=scan['scan_id'],target=t,payload=notification_payload(scan)) for t in targets]

    def claim(self,tenant_id,kinds):
        """One delivery per transaction; independent dispatchers skip held rows."""
        with self.transaction(tenant_id) as db:
            row=db.execute('''SELECT id,kind,job_id,scan_id,target_id,target_fingerprint,payload,attempts
                FROM delivery_events WHERE tenant_id=%s AND kind=ANY(%s)
                AND ((status='pending' AND next_attempt_at<=clock_timestamp()) OR (status='leased' AND lease_until<=clock_timestamp()))
                ORDER BY next_attempt_at,id LIMIT 1 FOR UPDATE SKIP LOCKED''',(tenant_id,list(kinds))).fetchone()
            if not row:
                return None
            event_id,kind,job_id,scan_id,target_id,fingerprint,payload,attempts=row
            if attempts>=8:
                db.execute("UPDATE delivery_events SET status='dead_letter',error_code='attempt_limit',lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE id=%s",(event_id,))
                audit(db,tenant_id,event_id,'exhausted')
                if kind=='notification':
                    refresh_notification_status(db,tenant_id,job_id)
                return None
            token=uuid4()
            db.execute("UPDATE delivery_events SET status='leased',attempts=attempts+1,lease_token=%s,lease_until=clock_timestamp()+interval '60 seconds',updated_at=clock_timestamp() WHERE id=%s",(token,event_id))
            audit(db,tenant_id,event_id,'claimed')
            return dict(id=str(event_id),kind=kind,job_id=str(job_id) if job_id else None,scan_id=str(scan_id) if scan_id else None,
                        target_id=target_id,target_fingerprint=fingerprint,payload=payload,attempts=attempts+1,lease_token=str(token))

    def finish(self,tenant_id,event,*,outcome,error_code=None,retry_after=0):
        if outcome not in ('delivered','published','retry','dead_letter'):
            raise ValueError('Invalid delivery outcome')
        if error_code not in (None,'transport_unavailable','rate_limited','provider_unavailable','provider_rejected','target_changed','scope_revoked','attempt_limit'):
            raise ValueError('Invalid delivery error code')
        with self.transaction(tenant_id) as db:
            status='pending' if outcome=='retry' else outcome
            if status=='pending' and event['attempts']>=8:
                status='dead_letter'
            delay=900 if status=='published' else max(1,min(float(retry_after),3600))
            changed=db.execute('''UPDATE delivery_events SET status=%s,error_code=%s,next_attempt_at=clock_timestamp()+make_interval(secs=>%s),
                lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE tenant_id=%s AND id=%s AND status='leased'
                AND lease_token=%s AND lease_until>clock_timestamp() RETURNING job_id''',
                (status,error_code,delay,tenant_id,event['id'],event['lease_token'])).fetchone()
            if not changed:
                return False
            audit(db,tenant_id,event['id'],status)
            if event['kind']=='notification':
                refresh_notification_status(db,tenant_id,changed[0])
            return True

    def reconcile(self,tenant_id):
        """Recover published messages lost by Redis and crashed workers, using DB state."""
        with self.transaction(tenant_id) as db:
            rows=db.execute('''SELECT d.id,d.job_id,d.attempts
                FROM delivery_events d
                WHERE d.tenant_id=%s AND d.kind='scan' AND d.status='published' AND d.next_attempt_at<=clock_timestamp()
                ORDER BY d.next_attempt_at,d.id LIMIT 100 FOR UPDATE OF d SKIP LOCKED''',(tenant_id,)).fetchall()
            for event_id,job_id,attempts in rows:
                # Completion locks its job before its delivery row. Never wait
                # for that job while holding a delivery lock: skip active commits.
                job=db.execute("SELECT status,updated_at<clock_timestamp()-interval '15 minutes' FROM scan_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE SKIP LOCKED",(tenant_id,job_id)).fetchone()
                if not job:
                    continue
                job_status,stale=job
                if job_status=='running' and not stale:
                    db.execute("UPDATE delivery_events SET next_attempt_at=clock_timestamp()+interval '15 minutes' WHERE id=%s",(event_id,))
                    continue
                status='delivered' if job_status=='completed' else 'dead_letter' if job_status=='failed' or attempts>=8 else 'pending'
                if status=='dead_letter' and job_status in ('queued','running'):
                    db.execute("UPDATE scan_jobs SET status='failed',error_code='dispatch_limit',lease_token=NULL,updated_at=clock_timestamp() WHERE id=%s",(job_id,))
                if status=='pending' and job_status=='running':
                    # The hard task limit is 600s, Redis lease 660s. Fence the lost
                    # worker before a republish; active workers are never interrupted.
                    db.execute("UPDATE scan_jobs SET status='queued',lease_token=NULL,updated_at=clock_timestamp() WHERE id=%s",(job_id,))
                db.execute("UPDATE delivery_events SET status=%s,next_attempt_at=clock_timestamp(),updated_at=clock_timestamp(),error_code=%s WHERE id=%s",(status,'attempt_limit' if status=='dead_letter' else None,event_id))
                audit(db,tenant_id,event_id,'reconciled')
            return len(rows)

    def replay(self,tenant_id,event_id,actor):
        with self.transaction(tenant_id) as db:
            row=db.execute('SELECT status,kind,replay_count,job_id FROM delivery_events WHERE tenant_id=%s AND id=%s FOR UPDATE',(tenant_id,event_id)).fetchone()
            if not row:
                return None
            if row[0]!='dead_letter' or row[1]!='notification' or row[2]>=3:
                raise DeliveryConflict('Only dead-letter notifications with fewer than three replays can be retried')
            db.execute("UPDATE delivery_events SET status='pending',attempts=0,replay_count=replay_count+1,error_code=NULL,lease_token=NULL,lease_until=NULL,next_attempt_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=%s",(event_id,))
            audit(db,tenant_id,event_id,'replay_requested',actor)
            refresh_notification_status(db,tenant_id,row[3])
        return self.get(tenant_id,event_id)
