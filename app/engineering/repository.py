"""Tenant transactions for declared workloads and immutable, evidence-bound reviews.

All commands serialize with EnterpriseStore's tenant lock. No command dispatches
cloud writes or turns a declaration into measured evidence.
"""
from datetime import datetime, timezone
from uuid import uuid4

from app.cloud_scope import validate_finding_scope
from app.control_plane.plans import PlanVersion, digest
from app.enterprise_store import decode
from app.focus import authorized
from app.principals import actor
from app.resource_assessment import resource_key
from app.engineering.cursors import Cursors, context
from app.engineering.readiness import evaluate


class EngineeringError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def scopes(tenant):
    # An old service-key grant must not retain a removed configured subscription.
    return sorted(s for s in tenant.get('subscription_ids', []) if authorized('azure', s, tenant))


def owned(value):
    if value is None:
        raise EngineeringError('Resource not found', 404)
    return value


def expect(actual, expected):
    if expected is None:
        raise EngineeringError('If-Match is required', 428)
    if expected != actual:
        raise EngineeringError('The record changed; refresh before editing', 412)


class Engineering:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cursors = Cursors()

    def _workload(self, db, tenant, wid):
        row = db.execute('SELECT id,name,environment,provider,scope_id,owner,team,requirements,version,created_at,updated_at FROM engineering_workloads WHERE tenant_id=%s AND id=%s',
                         (tenant['tenant_id'], wid)).fetchone()
        if not row or row[4] not in scopes(tenant):
            raise EngineeringError('Resource not found', 404)
        keys = ('id','name','environment','provider','scope_id','owner','team','requirements','version','created_at','updated_at')
        value = dict(zip(keys, row))
        value.update(id=str(value['id']), tenant_id=tenant['tenant_id'], requirements=decode(value['requirements']),
                     created_at=str(value['created_at']), updated_at=str(value['updated_at']))
        return value

    def _event(self, db, tenant, wid, kind, payload, vid=None):
        eid, now = str(uuid4()), self.clock().isoformat()
        db.execute('INSERT INTO engineering_events(tenant_id,id,workload_id,version_id,kind,actor_hash,payload,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                   (tenant['tenant_id'],eid,wid,vid,kind,actor(tenant),db.json(payload),now))
        db.execute('INSERT INTO engineering_outbox(tenant_id,event_id,created_at) VALUES(%s,%s,%s)', (tenant['tenant_id'],eid,now))

    def _command(self, tenant, operation, key, payload, action):
        fingerprint = digest(payload)
        with self.store.transaction(tenant['tenant_id'], write=True) as db:
            prior = db.execute('SELECT fingerprint,workload_id,response FROM engineering_commands WHERE tenant_id=%s AND actor_hash=%s AND operation_id=%s AND request_key=%s',
                               (tenant['tenant_id'],actor(tenant),operation,key)).fetchone()
            if prior:
                self._workload(db,tenant,str(prior[1]))  # Reauthorize even identical retries.
                if prior[0] != fingerprint:
                    raise EngineeringError('Idempotency key was already used for different input')
                return decode(prior[2])
            result, wid = action(db)
            db.execute('INSERT INTO engineering_commands(tenant_id,actor_hash,operation_id,request_key,fingerprint,workload_id,response,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                       (tenant['tenant_id'],actor(tenant),operation,key,fingerprint,wid,db.json(result),self.clock().isoformat()))
            return result

    def _page(self, tenant, operation, limit, cursor, query):
        if not 1 <= limit <= 200:
            raise EngineeringError('Page size must be between 1 and 200',422)
        binding = context(tenant,operation,limit)
        try:
            after = self.cursors.decode(cursor,binding) if cursor else '00000000-0000-0000-0000-000000000000'
        except ValueError as error:
            raise EngineeringError(str(error),422) from None
        with self.store.transaction(tenant['tenant_id']) as db:
            items = query(db,after,limit+1)
        return dict(items=items[:limit], next_cursor=self.cursors.encode(items[limit-1]['id'],binding) if len(items)>limit else None)

    def workloads(self, tenant, limit=50, cursor=None):
        def query(db, after, size):
            allowed = scopes(tenant)
            if not allowed:
                return []
            rows = db.execute('SELECT id FROM engineering_workloads WHERE tenant_id=%s AND id>%s AND provider=%s AND scope_id IN ('+','.join('%s' for _ in allowed)+') ORDER BY id LIMIT %s',
                              (tenant['tenant_id'],after,'azure',*allowed,size)).fetchall()
            return [self._workload(db,tenant,str(r[0])) for r in rows]
        return self._page(tenant,'workloads.list',limit,cursor,query)

    def detail(self, tenant, wid):
        with self.store.transaction(tenant['tenant_id']) as db:
            return self._workload(db,tenant,wid)

    def create(self, tenant, value, key):
        payload = value.model_dump(mode='json')
        def action(db):
            if str(value.scope_id) not in scopes(tenant):
                raise EngineeringError('Resource not found',404)
            if db.execute('SELECT count(*) FROM engineering_workloads WHERE tenant_id=%s',(tenant['tenant_id'],)).fetchone()[0] >= 1000:
                raise EngineeringError('Workload limit reached',429)
            wid, now = str(uuid4()), self.clock().isoformat()
            requirements = {k:v for k,v in payload.items() if k.endswith('_reference')}
            db.execute('INSERT INTO engineering_workloads(tenant_id,id,name,environment,provider,scope_id,owner,team,requirements,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (tenant['tenant_id'],wid,value.name,value.environment,'azure',str(value.scope_id),value.owner,value.team,db.json(requirements),now,now))
            self._event(db,tenant,wid,'workload.created',dict(version=1,scope_id=str(value.scope_id),workload=self._workload(db,tenant,wid)))
            return self._workload(db,tenant,wid),wid
        return self._command(tenant,'workloads.create',key,payload,action)

    def update(self, tenant, wid, value, key, expected):
        changes = value.model_dump(mode='json',exclude_unset=True)
        def action(db):
            current = self._workload(db,tenant,wid)
            expect(current['version'],expected)
            for k,v in changes.items():
                if k.endswith('_reference'):
                    current['requirements'][k]=v
                else:
                    current[k]=v
            db.execute('UPDATE engineering_workloads SET name=%s,environment=%s,owner=%s,team=%s,requirements=%s,version=version+1,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=%s',
                       (current['name'],current['environment'],current['owner'],current['team'],db.json(current['requirements']),self.clock().isoformat(),tenant['tenant_id'],wid,expected))
            self._event(db,tenant,wid,'workload.updated',dict(version=expected+1,changed_fields=sorted(changes),workload=self._workload(db,tenant,wid)))
            return self._workload(db,tenant,wid),wid
        return self._command(tenant,'workloads.update',key,dict(workload_id=wid,expected=expected,changes=changes),action)

    def _observation(self, db, tenant, workload, sid, rid):
        row = owned(db.execute('SELECT payload FROM scans WHERE tenant_id=%s AND id=%s',(tenant['tenant_id'],sid)).fetchone())
        scan = decode(row[0])
        if scan.get('status')!='completed' or scan.get('data_origin')=='legacy_synthetic' or scan.get('mode')=='demo':
            raise EngineeringError('Select a completed live observation')
        resource = next((r for r in [*scan.get('inventory',[]),*scan.get('findings',[])] if resource_key(r)==rid),None)
        owned(resource)
        if resource.get('cloud_provider','azure')!='azure' or resource.get('subscription_id')!=workload['scope_id']:
            raise EngineeringError('Resource not found',404)
        try:
            validate_finding_scope(resource,tenant)
        except (ValueError,KeyError):
            raise EngineeringError('Resource not found',404) from None
        return scan,resource

    def add_member(self, tenant, wid, value, key, expected):
        def action(db):
            workload = self._workload(db,tenant,wid)
            expect(workload['version'],expected)
            _,resource = self._observation(db,tenant,workload,str(value.scan_id),value.resource_key)
            if db.execute('SELECT 1 FROM engineering_members WHERE tenant_id=%s AND workload_id=%s AND resource_key=%s', (tenant['tenant_id'],wid,value.resource_key)).fetchone():
                raise EngineeringError('Resource is already a member; select a new observation when revising its plan')
            if db.execute('SELECT count(*) FROM engineering_members WHERE tenant_id=%s AND workload_id=%s',(tenant['tenant_id'],wid)).fetchone()[0]>=1000:
                raise EngineeringError('Workload resource limit reached',429)
            mid,now = str(uuid4()), self.clock().isoformat()
            db.execute('INSERT INTO engineering_members(tenant_id,id,workload_id,scan_id,resource_key,resource_id,resource_type,resource_name,evidence_digest,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (tenant['tenant_id'],mid,wid,str(value.scan_id),value.resource_key,resource['resource_id'],resource['resource_type'],resource.get('resource_name') or resource['resource_id'],digest(resource),now))
            db.execute('UPDATE engineering_workloads SET version=version+1,updated_at=%s WHERE tenant_id=%s AND id=%s',(now,tenant['tenant_id'],wid))
            self._event(db,tenant,wid,'workload.member_added',dict(member_id=mid,scan_id=str(value.scan_id),workload_version=expected+1))
            return dict(id=mid,workload_id=wid,workload_version=expected+1),wid
        return self._command(tenant,'members.create',key,dict(workload_id=wid,expected=expected,**value.model_dump(mode='json')),action)

    def members(self, tenant, wid, limit=50, cursor=None):
        def query(db, after, size):
            self._workload(db,tenant,wid)
            rows=db.execute('SELECT id,scan_id,resource_key,resource_id,resource_type,resource_name,evidence_digest,created_at FROM engineering_members WHERE tenant_id=%s AND workload_id=%s AND id>%s ORDER BY id LIMIT %s', (tenant['tenant_id'],wid,after,size)).fetchall()
            keys=('id','scan_id','resource_key','resource_id','resource_type','resource_name','evidence_digest','created_at')
            return [dict(zip(keys,map(str,r))) for r in rows]
        return self._page(tenant,'members.list:'+wid,limit,cursor,query)

    def _plan(self, db, tenant, pid):
        row=owned(db.execute('SELECT workload_id FROM engineering_plan_links WHERE tenant_id=%s AND plan_id=%s',(tenant['tenant_id'],pid)).fetchone())
        return self._workload(db,tenant,str(row[0]))

    def _version(self, row, workload):
        value=dict(zip(('id','plan_id','version','identity_digest','parameters','state','created_at'),row))
        value.update(id=str(value['id']),plan_id=str(value['plan_id']),created_at=str(value['created_at']),parameters=decode(value['parameters']),workload_id=workload['id'])
        value['context_changed']=value['parameters']['workload_version']!=workload['version']
        value['execution_enabled']=False
        return value

    def versions(self, tenant, pid, limit=50, cursor=None):
        def query(db,after,size):
            workload=self._plan(db,tenant,pid)
            rows=db.execute('SELECT id,plan_id,version,identity_digest,parameters,state,created_at FROM cp_plan_versions WHERE tenant_id=%s AND plan_id=%s AND id>%s ORDER BY id LIMIT %s',(tenant['tenant_id'],pid,after,size)).fetchall()
            return [self._version(r,workload) for r in rows]
        return self._page(tenant,'versions.list:'+pid,limit,cursor,query)

    def plans(self, tenant, wid, limit=50, cursor=None):
        def query(db,after,size):
            workload=self._workload(db,tenant,wid)
            rows=db.execute('SELECT v.id,v.plan_id,v.version,v.identity_digest,v.parameters,v.state,v.created_at FROM cp_plan_versions v JOIN engineering_plan_links l ON l.tenant_id=v.tenant_id AND l.plan_id=v.plan_id WHERE l.tenant_id=%s AND l.workload_id=%s AND l.plan_id>%s AND v.version=(SELECT max(p.version) FROM cp_plan_versions p WHERE p.tenant_id=v.tenant_id AND p.plan_id=v.plan_id) ORDER BY l.plan_id LIMIT %s',(tenant['tenant_id'],wid,after,size)).fetchall()
            items=[]
            for row in rows:
                version=self._version(row,workload)
                items.append(dict(id=version['plan_id'],latest=version))
            return items
        return self._page(tenant,'plans.list:'+wid,limit,cursor,query)

    def save_plan(self, tenant, wid, value, key, expected, pid=None):
        payload=value.model_dump(mode='json')
        def action(db):
            workload=self._workload(db,tenant,wid)
            expect(workload['version'],expected)
            plan_id=pid or str(uuid4())
            version=1
            if pid:
                if self._plan(db,tenant,pid)['id']!=wid:
                    raise EngineeringError('Resource not found',404)
                latest=db.execute('SELECT max(version) FROM cp_plan_versions WHERE tenant_id=%s AND plan_id=%s',(tenant['tenant_id'],pid)).fetchone()[0]
                if latest!=value.parent_version:
                    raise EngineeringError('Plan changed; refresh before creating a revision')
                version=latest+1
                if version>1000:
                    raise EngineeringError('Plan revision limit reached',429)
            elif db.execute('SELECT count(*) FROM engineering_plan_links WHERE tenant_id=%s AND workload_id=%s',(tenant['tenant_id'],wid)).fetchone()[0]>=1000:
                raise EngineeringError('Workload plan limit reached',429)
            member=owned(db.execute('SELECT scan_id,resource_key FROM engineering_members WHERE tenant_id=%s AND workload_id=%s AND id=%s',(tenant['tenant_id'],wid,str(value.member_id))).fetchone())
            sid=str(value.scan_id or member[0])
            scan,resource=self._observation(db,tenant,workload,sid,member[1])
            readiness=evaluate(resource,scan,workload,action=value.action,candidate_sku=value.candidate_sku,now=self.clock())
            parameters=dict(schema_version=1,objective=value.objective,action=value.action,candidate_sku=value.candidate_sku,
                            workload_version=workload['version'],member_id=str(value.member_id),scan_id=sid,resource_key=member[1],readiness=readiness)
            identity=PlanVersion(plan_id,version,(str(value.member_id),),parameters,readiness['policy_digest'],readiness['evidence_digest']).identity()
            vid,now=str(uuid4()),self.clock().isoformat()
            if not pid:
                db.execute('INSERT INTO cp_plans(id,tenant_id,objective,owner_hash,created_at) VALUES(%s,%s,%s,%s,%s)',(plan_id,tenant['tenant_id'],value.objective,actor(tenant),now))
                db.execute('INSERT INTO engineering_plan_links(tenant_id,plan_id,workload_id,created_at) VALUES(%s,%s,%s,%s)',(tenant['tenant_id'],plan_id,wid,now))
            db.execute('INSERT INTO cp_plan_versions(id,tenant_id,plan_id,version,identity_digest,targets,parameters,policy_digest,evidence_digest,state,created_by_hash,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (vid,tenant['tenant_id'],plan_id,version,identity,db.json([str(value.member_id)]),db.json(parameters),readiness['policy_digest'],readiness['evidence_digest'],'evidence_required',actor(tenant),now,now))
            db.execute('INSERT INTO engineering_plan_targets(tenant_id,version_id,workload_id,member_id,scan_id) VALUES(%s,%s,%s,%s,%s)',(tenant['tenant_id'],vid,wid,str(value.member_id),sid))
            self._event(db,tenant,wid,'plan.version_created',dict(plan_id=plan_id,version=version,identity_digest=identity),vid)
            return self._version((vid,plan_id,version,identity,parameters,'evidence_required',now),workload),wid
        return self._command(tenant,'plans.revise' if pid else 'plans.create',key,dict(workload_id=wid,plan_id=pid,expected=expected,**payload),action)

    def events(self, tenant, wid, limit=50, cursor=None):
        def query(db,after,size):
            self._workload(db,tenant,wid)
            rows=db.execute('SELECT id,kind,actor_hash,payload,created_at FROM engineering_events WHERE tenant_id=%s AND workload_id=%s AND id>%s ORDER BY id LIMIT %s',(tenant['tenant_id'],wid,after,size)).fetchall()
            return [dict(id=str(r[0]),kind=r[1],actor_hash=r[2],payload=decode(r[3]),created_at=str(r[4])) for r in rows]
        return self._page(tenant,'events.list:'+wid,limit,cursor,query)
