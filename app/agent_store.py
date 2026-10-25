"""Durable leases and single-use step permits; uncertain writes are never replayed."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

from app.agent_contract import binding, digest, program_hash, render_code, validate_plan
from app.enterprise_store import decode
from app.principals import actor, visible
from app.telemetry_contract import moment

COLUMNS = 'id,tenant_id,provider,scope_id,resource_id,scan_id,state,version,payload,created_at,updated_at'
TERMINAL = {'succeeded','failed','rejected','cancelled','needs_reconciliation','approval_expired'}


class AgentConflict(ValueError): pass


def unreconciled(payload):
    steps=(payload.get('plan') or {}).get('steps',[])
    paired=any(s['operation']=='gitops.terraform.sync' for s in steps)
    return any(s.get('state')=='started' for s in payload.get('steps',[])) or bool(paired and any(
        s.get('state')=='succeeded' and steps[i]['operation'] in ('tags.merge','labels.merge','annotations.merge')
        for i,s in enumerate(payload.get('steps',[]))))


def configured(task, tenant):
    keys = {'azure':('subscription_ids',None),'aws':('aws_accounts','account_id'),
            'gcp':('gcp_projects','project_id'),'kubernetes':('kubernetes_clusters','cluster_id')}
    key, field = keys[task['provider']]
    values = tenant.get(key,[])
    return task['scope_id'].lower() in {str(v.get(field) if field else v).lower() for v in values}


class AgentRepository:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _row(self, db, tid, task_id):
        row = db.execute(f'SELECT {COLUMNS} FROM agent_tasks WHERE tenant_id=%s AND id=%s', (tid, task_id)).fetchone()
        if not row: return None
        task = dict(zip(COLUMNS.split(','), row))
        for key in ('id','tenant_id','scan_id','created_at','updated_at'): task[key] = str(task[key])
        task['payload'] = decode(task['payload'])
        return task

    def _event(self, db, task, action, who, details):
        db.execute('INSERT INTO agent_task_events(id,tenant_id,task_id,version,action,actor,payload,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (str(uuid4()),task['tenant_id'],task['id'],task['version'],action,who,db.json(details),self.clock().isoformat()))

    def _save(self, db, task, state, action, who, details=None):
        version = task['version']
        task.update(state=state, version=version+1, updated_at=self.clock().isoformat())
        changed = db.execute('UPDATE agent_tasks SET state=%s,version=%s,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=%s',
            (state,task['version'],db.json(task['payload']),task['updated_at'],task['tenant_id'],task['id'],version)).rowcount
        if changed != 1: raise AgentConflict('Task changed. Refresh before continuing.')
        self._event(db,task,action,who,details or {})
        return task

    def _owned(self, db, tenant, task_id, version=None):
        task = self._row(db,tenant['tenant_id'],task_id)
        if not task or not visible(task,tenant) or not configured(task,tenant): return None
        if version is not None and task['version'] != version: raise AgentConflict('Task changed. Refresh before continuing.')
        return task

    @staticmethod
    def public(task):
        if task is None: return None
        import copy
        result = copy.deepcopy(task)
        result['payload'].pop('lease',None)
        expiry=moment(result['payload'].get('data_retention_expires_at'))
        if result['payload'].get('data_content_expired') or (expiry and expiry<=datetime.now(timezone.utc)):
            result['payload'].update(intent='[AI CONTENT EXPIRED]',plan=None,steps=[],connector_bindings=[],approval=None,data_content_expired=True)
        return result

    def create(self, tenant, scan, resource, request):
        tid = tenant['tenant_id']; now = self.clock().isoformat(); fingerprint = digest(request)
        with self.store.transaction(tid,write=True) as db:
            prior = db.execute('SELECT id,fingerprint FROM agent_tasks WHERE tenant_id=%s AND request_key=%s',(tid,request['request_key'])).fetchone()
            if prior:
                if prior[1] != fingerprint: raise AgentConflict('Idempotency key belongs to another task.')
                return self.public(self._owned(db,tenant,str(prior[0])))
            if db.execute('SELECT count(*) FROM agent_tasks WHERE tenant_id=%s AND created_at>=%s',
                (tid,(self.clock()-timedelta(days=1)).isoformat())).fetchone()[0] >= 100:
                raise AgentConflict('Workspace task limit is 100 new tasks per day.')
            task_id = str(uuid4())
            payload = dict(intent=request['intent'],connector_ids=sorted(request['connector_ids']),target_id=request['target_id'],
                resource_type=resource['resource_type'],draft_key=str(uuid4()),draft_attempts=0,plan=None,plan_hash=None,
                approval=None,steps=[],data_notice='The explicit task instruction and resource type go to the approved model; credentials and resource identifiers are excluded.')
            from app.agent_contract import expected_state
            payload['expected_state']=expected_state(resource)
            payload['data_retention_expires_at']=(self.clock()+timedelta(days=request.get('_retention_days',7))).isoformat()
            db.execute('''INSERT INTO agent_tasks(id,tenant_id,provider,scope_id,resource_id,scan_id,request_key,fingerprint,state,version,payload,actor,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'draft_queued',1,%s,%s,%s,%s)''',
                (task_id,tid,resource.get('cloud_provider','azure'),resource.get('scope_id') or resource['subscription_id'],resource['resource_id'],scan['scan_id'],
                 request['request_key'],fingerprint,db.json(payload),actor(tenant),now,now))
            task = self._row(db,tid,task_id)
            self._event(db,task,'task_requested',actor(tenant),dict(scan_id=scan['scan_id']))
            return self.public(task)

    def list(self, tenant, limit=50):
        with self.store.transaction(tenant['tenant_id']) as db:
            rows = db.execute(f'SELECT id FROM agent_tasks WHERE tenant_id=%s ORDER BY created_at DESC,id DESC LIMIT 1000',(tenant['tenant_id'],)).fetchall()
            tasks = [self._row(db,tenant['tenant_id'],str(row[0])) for row in rows]
        return [self.public(t) for t in tasks if visible(t,tenant) and configured(t,tenant)][:limit]

    def get(self, tenant, task_id):
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            task = self._owned(db,tenant,task_id)
            if task:
                self._expire(db,task)
                rows = db.execute('SELECT version,action,actor,payload,created_at FROM agent_task_events WHERE tenant_id=%s AND task_id=%s ORDER BY version',(tenant['tenant_id'],task_id)).fetchall()
                task['events'] = [dict(version=r[0],action=r[1],actor=r[2],payload=decode(r[3]),created_at=str(r[4])) for r in rows]
        return self.public(task)

    def _expire(self, db, task):
        p=task['payload'];now=self.clock()
        if task['state']=='approved' and moment((p.get('approval') or {}).get('expires_at')) and moment(p['approval']['expires_at'])<=now:
            self._save(db,task,'approval_expired','approval_expired','gateway')
        elif task['state'] in {'drafting','running','cancel_requested'} and moment((p.get('lease') or {}).get('expires_at')) and moment(p['lease']['expires_at'])<=now:
            state='needs_reconciliation' if unreconciled(p) else 'failed'
            self._save(db,task,state,'lease_expired','gateway',dict(automatic_retry=False))

    def review(self, tenant, task_id, version, decision, expected_hash, minutes, catalog):
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            task = self._owned(db,tenant,task_id,version)
            if not task: return None
            p = task['payload']
            if decision == 'cancel':
                if task['state'] in TERMINAL: raise AgentConflict('This task is already final.')
                state = 'cancel_requested' if any(s['state']=='started' for s in p['steps']) else 'needs_reconciliation' if unreconciled(p) else 'cancelled'
                return self.public(self._save(db,task,state,'cancellation_requested',actor(tenant)))
            if decision == 'redraft':
                if moment(p.get('data_retention_expires_at')) and moment(p['data_retention_expires_at'])<=self.clock():raise AgentConflict('Task data expired. Create a new explicit instruction instead of reusing expired content.')
                attempted_write = p.get('plan') and any(s['state']!='pending' and p['plan']['steps'][i]['operation'] not in ('resource.inspect','workload.inspect') for i,s in enumerate(p['steps']))
                if task['state'] not in {'awaiting_approval','rejected','failed','approval_expired'} or any(s['state']=='started' for s in p['steps']) or attempted_write:
                    raise AgentConflict('This task cannot be redrafted; reconcile any uncertain action independently.')
                if p['draft_attempts'] >= 5: raise AgentConflict('Draft limit reached for this task.')
                p.update(draft_key=str(uuid4()),plan=None,plan_hash=None,approval=None,steps=[])
                return self.public(self._save(db,task,'draft_queued','redraft_requested',actor(tenant)))
            if task['state'] != 'awaiting_approval': raise AgentConflict('Only a drafted plan can be reviewed.')
            if not expected_hash or expected_hash != p['plan_hash'] or program_hash(task,p['plan'],catalog) != expected_hash:
                raise AgentConflict('Plan or connector configuration changed; request a new draft.')
            validate_plan(p['plan'],task,catalog)
            if decision == 'approve':
                if moment(p.get('data_retention_expires_at')) and moment(p['data_retention_expires_at'])<=self.clock():raise AgentConflict('AI task content expired under data governance. Create a new explicit task.')
                p['approval'] = dict(actor=actor(tenant),plan_hash=expected_hash,approved_at=self.clock().isoformat(),
                    expires_at=(self.clock()+timedelta(minutes=minutes)).isoformat())
            return self.public(self._save(db,task,'approved' if decision=='approve' else 'rejected',decision,actor(tenant),dict(plan_hash=expected_hash)))

    def claim(self, tenant, worker, catalog):
        tid = tenant['tenant_id']; now = self.clock()
        with self.store.transaction(tid,write=True) as db:
            rows = db.execute("SELECT id FROM agent_tasks WHERE tenant_id=%s AND state IN ('draft_queued','drafting','approved','running','cancel_requested') ORDER BY CASE WHEN state='approved' THEN 0 ELSE 1 END,created_at,id LIMIT 1000",(tid,)).fetchall()
            for row in rows:
                task = self._row(db,tid,str(row[0])); p = task['payload']
                if moment(p.get('data_retention_expires_at')) and moment(p['data_retention_expires_at'])<=now:
                    p['data_content_expired']=True
                    state='needs_reconciliation' if unreconciled(p) else 'cancelled'
                    self._save(db,task,state,'task_data_expired','gateway');continue
                if task['state'] in {'drafting','running','cancel_requested'}:
                    self._expire(db,task)
                    continue
                if not visible(task,tenant) or not configured(task,tenant) or not set(p['connector_ids']) <= set(worker['connector_ids']): continue
                if task['state'] == 'approved':
                    approval = p.get('approval') or {}
                    if not moment(approval.get('expires_at')) or moment(approval['expires_at']) <= now:
                        self._save(db,task,'approval_expired','approval_expired','gateway'); continue
                    try:
                        validate_plan(p['plan'],task,catalog)
                        if program_hash(task,p['plan'],catalog) != approval.get('plan_hash'): raise ValueError()
                    except ValueError:
                        self._save(db,task,'approval_expired','connector_grant_changed','gateway'); continue
                token = secrets.token_urlsafe(32)
                p['lease'] = dict(worker_id=worker['id'],token_hash=hashlib.sha256(token.encode()).hexdigest(),started_at=now.isoformat(),expires_at=(now+timedelta(seconds=120)).isoformat())
                phase = 'draft' if task['state']=='draft_queued' else 'execute'
                if phase == 'draft': p['draft_attempts'] += 1
                self._save(db,task,'drafting' if phase=='draft' else 'running','worker_assigned','worker:'+worker['id'],dict(phase=phase))
                return dict(task=self.public(task),phase=phase,lease_token=token,lease_seconds=120,code=render_code(p['plan']) if phase=='execute' else None,
                    connectors=[c.model_dump() for c in catalog if c.id in p['connector_ids']])
        return None

    def _leased(self, db, tenant, task_id, worker, token):
        task = self._owned(db,tenant,task_id)
        lease = task['payload'].get('lease',{}) if task else {}
        if (not task or lease.get('worker_id') != worker['id'] or not secrets.compare_digest(lease.get('token_hash',''),hashlib.sha256(token.encode()).hexdigest())
                or not moment(lease.get('expires_at')) or moment(lease['expires_at']) <= self.clock()):
            raise AgentConflict('Worker lease is invalid or expired.')
        if not set(task['payload']['connector_ids']) <= set(worker['connector_ids']): raise AgentConflict('Worker connector grant changed.')
        return task

    def heartbeat(self, tenant, task_id, worker, token):
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            task = self._leased(db,tenant,task_id,worker,token)
            if task['state'] not in {'drafting','running','cancel_requested'}: raise AgentConflict('Task is no longer assigned.')
            if (self.clock()-moment(task['payload']['lease']['started_at'])).total_seconds()>900: raise AgentConflict('Maximum assignment duration reached.')
            task['payload']['lease']['expires_at'] = (self.clock()+timedelta(seconds=120)).isoformat()
            db.execute('UPDATE agent_tasks SET payload=%s WHERE tenant_id=%s AND id=%s',(db.json(task['payload']),tenant['tenant_id'],task_id))
            return dict(state=task['state'])

    def draft_input(self, tenant, task_id, worker, token):
        with self.store.transaction(tenant['tenant_id']) as db:
            task = self._leased(db,tenant,task_id,worker,token)
            if task['state'] != 'drafting': raise AgentConflict('Task is not assigned for drafting.')
            return task

    def save_draft(self, tenant, task_id, worker, token, plan, catalog):
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            task = self._leased(db,tenant,task_id,worker,token)
            if task['state'] != 'drafting': raise AgentConflict('Task is no longer assigned for drafting.')
            p = task['payload']; p['plan'] = validate_plan(plan,task,catalog)
            p.update(plan_hash=program_hash(task,p['plan'],catalog),steps=[{'state':'pending'} for _ in p['plan']['steps']],
                connector_bindings=[binding(c) for c in catalog if c.id in {s['connector_id'] for s in p['plan']['steps']}])
            return self.public(self._save(db,task,'awaiting_approval','ai_plan_drafted','worker:'+worker['id'],dict(plan_hash=p['plan_hash'],step_count=len(p['plan']['steps']))))

    def step(self, tenant, task_id, worker, token, index, action, plan_hash, outcome, catalog):
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            task = self._leased(db,tenant,task_id,worker,token); p = task['payload']
            if task['state'] not in {'running','cancel_requested'} or not 0 <= index < len(p['steps']): raise AgentConflict('Task is not executing this step.')
            if plan_hash != p['plan_hash']: raise AgentConflict('Approved plan hash does not match.')
            step = p['steps'][index]
            if action == 'start':
                approval = p.get('approval') or {}
                if task['state'] != 'running' or moment(approval.get('expires_at')) is None or moment(approval['expires_at']) <= self.clock():
                    raise AgentConflict('Approval expired or task was cancelled; no new action is permitted.')
                if moment(p.get('data_retention_expires_at')) and moment(p['data_retention_expires_at'])<=self.clock():raise AgentConflict('Task data expired; no new action is permitted.')
                validate_plan(p['plan'],task,catalog)
                if program_hash(task,p['plan'],catalog) != plan_hash: raise AgentConflict('Connector configuration changed; approval is invalid.')
                if step['state'] != 'pending' or any(s['state']!='succeeded' for s in p['steps'][:index]):
                    raise AgentConflict('Step permits are ordered and single-use; uncertain work cannot be replayed.')
                step.update(state='started',started_at=self.clock().isoformat())
                self._save(db,task,'running','step_started','worker:'+worker['id'],dict(index=index,plan_hash=plan_hash))
                return dict(permitted=True,index=index,plan_hash=plan_hash)
            if step['state'] != 'started': raise AgentConflict('Only a started step can report its outcome.')
            step.update(state=outcome['status'],result=outcome,completed_at=self.clock().isoformat())
            state = ('needs_reconciliation' if outcome['status']=='uncertain' else 'failed' if outcome['status']=='failed'
                else ('needs_reconciliation' if unreconciled(p) else 'cancelled') if task['state']=='cancel_requested' else 'succeeded' if index==len(p['steps'])-1 else 'running')
            return self.public(self._save(db,task,state,'step_completed','worker:'+worker['id'],dict(index=index,outcome=outcome)))

    def fail(self, tenant, task_id, worker, token):
        with self.store.transaction(tenant['tenant_id'],write=True) as db:
            task = self._leased(db,tenant,task_id,worker,token)
            if task['state'] not in {'drafting','running','cancel_requested'}: raise AgentConflict('Task is no longer assigned.')
            p=task['payload']
            state = 'needs_reconciliation' if unreconciled(p) else 'failed'
            return self.public(self._save(db,task,state,'worker_stopped','worker:'+worker['id'],dict(automatic_retry=False)))
