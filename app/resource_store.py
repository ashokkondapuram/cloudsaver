"""Tenant-scoped persistence for resource AI batches, follow-up questions and reviewer decisions."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.enterprise_store import decode

ACTIVE = ('queued', 'running', 'waiting_for_budget')
STUCK_AFTER = timedelta(minutes=15)
BATCH = 'id,scan_id,target_id,status,total,resume_after,created_at,updated_at'


class ResourceConflict(RuntimeError):
    pass


def iso(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def utcnow():
    return datetime.now(timezone.utc)


class ResourceStore:
    def __init__(self, store):
        self.store = store

    # Batches

    def create_batch(self, tenant_id, *, scan_id, target_id, request_key, actor, items):
        now = utcnow().isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            prior = db.execute('SELECT id,scan_id FROM ai_batches WHERE tenant_id=%s AND request_key=%s', (tenant_id, request_key)).fetchone()
            if prior:
                if str(prior[1]) != scan_id:
                    raise ResourceConflict('Idempotency key belongs to a different batch')
                return self._batch(db, tenant_id, str(prior[0]))
            if db.execute(f"SELECT 1 FROM ai_batches WHERE tenant_id=%s AND scan_id=%s AND status IN {ACTIVE}", (tenant_id, scan_id)).fetchone():
                raise ResourceConflict('An AI batch is already active for this scan')
            batch_id = str(uuid4())
            db.execute('''INSERT INTO ai_batches(id,tenant_id,request_key,scan_id,target_id,status,total,actor,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s)''', (batch_id, tenant_id, request_key, scan_id, target_id, len(items), actor, now, now))
            for key, digest in items:
                db.execute('''INSERT INTO ai_batch_items(id,tenant_id,batch_id,resource_key,evidence_digest,status,updated_at)
                    VALUES (%s,%s,%s,%s,%s,'queued',%s)''', (str(uuid4()), tenant_id, batch_id, key, digest, now))
            return self._batch(db, tenant_id, batch_id)

    def _counts(self, db, tenant_id, batch_id):
        rows = db.execute('SELECT status,count(*) FROM ai_batch_items WHERE tenant_id=%s AND batch_id=%s GROUP BY status', (tenant_id, batch_id)).fetchall()
        counts = dict(queued=0, running=0, completed=0, failed=0, skipped=0, uncertain=0, cancelled=0)
        counts.update({status: count for status, count in rows})
        return counts

    def _batch(self, db, tenant_id, batch_id, *, items=False):
        row = db.execute(f'SELECT {BATCH} FROM ai_batches WHERE tenant_id=%s AND id=%s', (tenant_id, batch_id)).fetchone()
        if not row:
            return None
        batch = {k: iso(v) for k, v in zip(BATCH.split(','), row)}
        batch['id'], batch['scan_id'] = str(batch['id']), str(batch['scan_id'])
        batch['counts'] = self._counts(db, tenant_id, batch_id)
        if items:
            batch['items'] = [dict(resource_key=r[0].strip(), status=r[1], reason=r[2], attempt_id=str(r[3]) if r[3] else None, updated_at=iso(r[4]))
                              for r in db.execute('''SELECT resource_key,status,reason,attempt_id,updated_at FROM ai_batch_items
                                  WHERE tenant_id=%s AND batch_id=%s ORDER BY resource_key''', (tenant_id, batch_id)).fetchall()]
        return batch

    def batch(self, tenant_id, batch_id):
        with self.store.transaction(tenant_id) as db:
            return self._batch(db, tenant_id, batch_id, items=True)

    def batches(self, tenant_id, *, scan_id=None, limit=20):
        with self.store.transaction(tenant_id) as db:
            ids = db.execute('''SELECT id FROM ai_batches WHERE tenant_id=%s AND (CAST(%s AS TEXT) IS NULL OR scan_id=%s)
                ORDER BY created_at DESC,id DESC LIMIT %s''', (tenant_id, scan_id, scan_id, limit)).fetchall()
            return [self._batch(db, tenant_id, str(r[0])) for r in ids]

    def cancel(self, tenant_id, batch_id):
        now = utcnow().isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            row = db.execute('SELECT status FROM ai_batches WHERE tenant_id=%s AND id=%s', (tenant_id, batch_id)).fetchone()
            if not row:
                return None
            if row[0] in ACTIVE:
                db.execute("UPDATE ai_batch_items SET status='cancelled',updated_at=%s WHERE tenant_id=%s AND batch_id=%s AND status='queued'", (now, tenant_id, batch_id))
                db.execute("UPDATE ai_batches SET status='cancelled',resume_after=NULL,updated_at=%s WHERE tenant_id=%s AND id=%s", (now, tenant_id, batch_id))
            return self._batch(db, tenant_id, batch_id, items=True)

    def due(self, tenant_id, now=None):
        """Active batches ready for work, after marking items stuck in running as uncertain."""
        now = now or utcnow()
        with self.store.transaction(tenant_id, write=True) as db:
            db.execute("""UPDATE ai_batch_items SET status='uncertain',reason='outcome_uncertain',updated_at=%s
                WHERE tenant_id=%s AND status='running' AND updated_at<%s""", (now.isoformat(), tenant_id, (now - STUCK_AFTER).isoformat()))
            rows = db.execute('''SELECT id FROM ai_batches WHERE tenant_id=%s AND (status IN ('queued','running')
                OR (status='waiting_for_budget' AND (resume_after IS NULL OR resume_after<=%s))) ORDER BY created_at''', (tenant_id, now.isoformat())).fetchall()
            return [str(r[0]) for r in rows]

    def claim(self, tenant_id, batch_id):
        """Move the next queued item to running, or complete the batch when nothing is left."""
        now = utcnow().isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            batch = db.execute('SELECT scan_id,target_id,status FROM ai_batches WHERE tenant_id=%s AND id=%s', (tenant_id, batch_id)).fetchone()
            if not batch or batch[2] not in ACTIVE:
                return None
            item = db.execute('''SELECT id,resource_key,evidence_digest FROM ai_batch_items WHERE tenant_id=%s AND batch_id=%s
                AND status='queued' ORDER BY resource_key LIMIT 1''', (tenant_id, batch_id)).fetchone()
            if not item:
                running = db.execute("SELECT 1 FROM ai_batch_items WHERE tenant_id=%s AND batch_id=%s AND status='running'", (tenant_id, batch_id)).fetchone()
                if not running:
                    db.execute("UPDATE ai_batches SET status='completed',resume_after=NULL,updated_at=%s WHERE tenant_id=%s AND id=%s", (now, tenant_id, batch_id))
                return None
            db.execute("UPDATE ai_batch_items SET status='running',updated_at=%s WHERE tenant_id=%s AND id=%s", (now, tenant_id, item[0]))
            db.execute("UPDATE ai_batches SET status='running',resume_after=NULL,updated_at=%s WHERE tenant_id=%s AND id=%s", (now, tenant_id, batch_id))
            return dict(id=str(item[0]), batch_id=batch_id, scan_id=str(batch[0]), target_id=batch[1],
                        resource_key=item[1].strip(), evidence_digest=item[2].strip())

    def finish(self, tenant_id, item_id, status, *, attempt_id=None, reason=None):
        with self.store.transaction(tenant_id, write=True) as db:
            db.execute("""UPDATE ai_batch_items SET status=%s,attempt_id=%s,reason=%s,updated_at=%s
                WHERE tenant_id=%s AND id=%s AND status='running'""", (status, attempt_id, reason, utcnow().isoformat(), tenant_id, item_id))

    def wait_for_budget(self, tenant_id, item, resume_after):
        now = utcnow().isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            db.execute("UPDATE ai_batch_items SET status='queued',updated_at=%s WHERE tenant_id=%s AND id=%s AND status='running'", (now, tenant_id, item['id']))
            db.execute("""UPDATE ai_batches SET status='waiting_for_budget',resume_after=%s,updated_at=%s
                WHERE tenant_id=%s AND id=%s AND status IN ('queued','running')""", (resume_after.isoformat(), now, tenant_id, item['batch_id']))

    def item_states(self, tenant_id, scan_id):
        """Latest batch item per resource for one scan."""
        with self.store.transaction(tenant_id) as db:
            rows = db.execute('''SELECT i.resource_key,i.status,i.reason,i.attempt_id FROM ai_batch_items i
                JOIN ai_batches b ON b.id=i.batch_id AND b.tenant_id=i.tenant_id
                WHERE i.tenant_id=%s AND b.scan_id=%s ORDER BY b.created_at,i.updated_at''', (tenant_id, scan_id)).fetchall()
        return {r[0].strip(): dict(status=r[1], reason=r[2], attempt_id=str(r[3]) if r[3] else None) for r in rows}

    # AI results

    def results(self, tenant_id, keys=None, *, limit=5000):
        """Latest completed resource assessment per resource key, across scans."""
        with self.store.transaction(tenant_id) as db:
            rows = db.execute('''SELECT metadata->>'resource_reference',id,response,created_at,scan_id FROM ai_inference_attempts
                WHERE tenant_id=%s AND status='completed' AND metadata->>'kind'='resource_assessment'
                ORDER BY created_at DESC,id DESC LIMIT %s''', (tenant_id, limit)).fetchall()
        latest = {}
        for key, attempt_id, response, created_at, scan_id in rows:
            if key in latest or (keys is not None and key not in keys):
                continue
            response = decode(response)
            advice = response['advice']
            latest[key] = dict(assessment_id=str(attempt_id), scan_id=str(scan_id), created_at=iso(created_at),
                               evidence_digest=response['evidence_digest'], risk_level=advice['risk_level'],
                               summary=advice['summary'], actions=advice.get('recommended_actions', []), response=response)
        return latest

    def result_history(self, tenant_id, key, limit=20):
        with self.store.transaction(tenant_id) as db:
            rows = db.execute('''SELECT id,scan_id,created_at,response FROM ai_inference_attempts WHERE tenant_id=%s AND status='completed'
                AND metadata->>'kind'='resource_assessment' AND metadata->>'resource_reference'=%s
                ORDER BY created_at DESC,id DESC LIMIT %s''', (tenant_id, key, limit)).fetchall()
        return [dict(assessment_id=str(r[0]), scan_id=str(r[1]), created_at=iso(r[2]), risk_level=decode(r[3])['advice']['risk_level'],
                     evidence_digest=decode(r[3])['evidence_digest'], model=decode(r[3])['model']) for r in rows]

    # Follow-up questions

    def followups(self, tenant_id, scan_id, key):
        with self.store.transaction(tenant_id) as db:
            rows = db.execute('''SELECT f.id,f.question,f.created_at,a.response FROM ai_followups f
                JOIN ai_inference_attempts a ON a.id=f.attempt_id AND a.tenant_id=f.tenant_id
                WHERE f.tenant_id=%s AND f.scan_id=%s AND f.resource_key=%s ORDER BY f.created_at,f.id''', (tenant_id, scan_id, key)).fetchall()
        return [dict(id=str(r[0]), question=r[1], created_at=iso(r[2]), answer=decode(r[3])['advice']) for r in rows]

    def followup_count(self, tenant_id, scan_id, key):
        with self.store.transaction(tenant_id) as db:
            return db.execute('SELECT count(*) FROM ai_followups WHERE tenant_id=%s AND scan_id=%s AND resource_key=%s', (tenant_id, scan_id, key)).fetchone()[0]

    def add_followup(self, tenant_id, *, scan_id, key, attempt_id, question, actor):
        with self.store.transaction(tenant_id, write=True) as db:
            if db.execute('SELECT 1 FROM ai_followups WHERE tenant_id=%s AND attempt_id=%s', (tenant_id, attempt_id)).fetchone():
                return
            db.execute('''INSERT INTO ai_followups(id,tenant_id,scan_id,resource_key,attempt_id,question,actor,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''', (str(uuid4()), tenant_id, scan_id, key, attempt_id, question, actor, utcnow().isoformat()))

    # Reviewer decisions

    DECISION = 'id,resource_key,scan_id,decision,note,defer_until,evidence_digest,actor,created_at'

    def _decision(self, row):
        result = {k: iso(v) for k, v in zip(self.DECISION.split(','), row)}
        result.update(id=str(result['id']), scan_id=str(result['scan_id']), resource_key=result['resource_key'].strip(),
                      evidence_digest=result['evidence_digest'].strip(), actor=result['actor'].strip())
        return result

    def decisions(self, tenant_id, key, limit=50):
        with self.store.transaction(tenant_id) as db:
            rows = db.execute(f'''SELECT {self.DECISION} FROM resource_decisions WHERE tenant_id=%s AND resource_key=%s
                ORDER BY created_at DESC,id DESC LIMIT %s''', (tenant_id, key, limit)).fetchall()
        return [self._decision(r) for r in rows]

    def latest_decisions(self, tenant_id, keys=None, limit=20000):
        with self.store.transaction(tenant_id) as db:
            rows = db.execute(f'SELECT {self.DECISION} FROM resource_decisions WHERE tenant_id=%s ORDER BY created_at DESC,id DESC LIMIT %s',
                              (tenant_id, limit)).fetchall()
        latest = {}
        for row in rows:
            decision = self._decision(row)
            if decision['resource_key'] not in latest and (keys is None or decision['resource_key'] in keys):
                latest[decision['resource_key']] = decision
        return latest

    def decide(self, tenant_id, *, key, scan_id, decision, note, defer_until, evidence_digest, actor):
        decision_id = str(uuid4())
        with self.store.transaction(tenant_id, write=True) as db:
            db.execute('''INSERT INTO resource_decisions(id,tenant_id,resource_key,scan_id,decision,note,defer_until,evidence_digest,actor,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (decision_id, tenant_id, key, scan_id, decision, note,
                                                             defer_until.isoformat() if defer_until else None, evidence_digest, actor, utcnow().isoformat()))
            row = db.execute(f'SELECT {self.DECISION} FROM resource_decisions WHERE tenant_id=%s AND id=%s', (tenant_id, decision_id)).fetchone()
        return self._decision(row)
