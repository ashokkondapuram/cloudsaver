"""Tenant-owned observability connectors, fenced collection jobs, append-only snapshots and resource correlation."""
import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.enterprise_store import decode
from app.v150_store import WorkflowConflict

MAX_CONNECTORS = 25
TERMINAL = {'completed', 'failed', 'partial', 'cancelled', 'expired'}
DUE_AFTER = {'hourly': timedelta(hours=1), 'daily': timedelta(days=1)}


def _now():
    return datetime.now(timezone.utc)


def _key(resource_id):
    return resource_id.lower() if resource_id.lower().startswith('/subscriptions/') else resource_id


def actor(tenant):
    return hashlib.sha256((tenant.get('user_id') or 'workspace-key:' + tenant['tenant_id']).encode()).hexdigest()


class ObservabilityStore:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _public(row):
        id, name, kind, config, enabled, version, created_at, updated_at = row
        return dict(decode(config), id=str(id), name=name, kind=kind, enabled=bool(enabled), version=int(version),
                    created_at=str(created_at), updated_at=str(updated_at))

    def connectors(self, tid, *, enabled_only=False):
        with self.store.transaction(tid) as db:
            rows = db.execute('SELECT id,name,kind,config,enabled,version,created_at,updated_at FROM observability_connectors '
                              'WHERE tenant_id=%s ORDER BY name,id LIMIT %s', (tid, MAX_CONNECTORS)).fetchall()
        items = [self._public(r) for r in rows]
        return [i for i in items if i['enabled']] if enabled_only else items

    def connector(self, tid, id):
        with self.store.transaction(tid) as db:
            row = db.execute('SELECT id,name,kind,config,enabled,version,created_at,updated_at FROM observability_connectors '
                             'WHERE tenant_id=%s AND id=%s', (tid, id)).fetchone()
        return self._public(row) if row else None

    def create(self, tenant, config):
        tid, now, id = tenant['tenant_id'], _now().isoformat(), str(uuid4())
        with self.store.transaction(tid, write=True) as db:
            if db.postgres:
                db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('observability-connectors:' + tid,))
            if db.execute('SELECT COUNT(*) FROM observability_connectors WHERE tenant_id=%s', (tid,)).fetchone()[0] >= MAX_CONNECTORS:
                raise WorkflowConflict(f'A workspace can have at most {MAX_CONNECTORS} observability connectors.')
            if db.execute('SELECT 1 FROM observability_connectors WHERE tenant_id=%s AND name=%s', (tid, config['name'])).fetchone():
                raise WorkflowConflict('Another connector already uses this name.')
            db.execute('INSERT INTO observability_connectors(id,tenant_id,name,kind,config,enabled,version,created_by_hash,created_at,updated_at) '
                       'VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s,%s)', (id, tid, config['name'], config['kind'], db.json(config), True, actor(tenant), now, now))
        return self.connector(tid, id)

    def update(self, tenant, id, config, version):
        tid = tenant['tenant_id']
        with self.store.transaction(tid, write=True) as db:
            if db.execute('SELECT 1 FROM observability_connectors WHERE tenant_id=%s AND name=%s AND id<>%s', (tid, config['name'], id)).fetchone():
                raise WorkflowConflict('Another connector already uses this name.')
            changed = db.execute('UPDATE observability_connectors SET name=%s,kind=%s,config=%s,version=version+1,updated_at=%s '
                                 'WHERE tenant_id=%s AND id=%s AND version=%s',
                                 (config['name'], config['kind'], db.json(config), _now().isoformat(), tid, id, version)).rowcount
        if not changed:
            if self.connector(tid, id) is None:
                return None
            raise WorkflowConflict('This connector changed since you opened it. Refresh and try again.')
        return self.connector(tid, id)

    def set_enabled(self, tid, id, enabled):
        with self.store.transaction(tid, write=True) as db:
            db.execute('UPDATE observability_connectors SET enabled=%s,version=version+1,updated_at=%s WHERE tenant_id=%s AND id=%s',
                       (enabled, _now().isoformat(), tid, id))
        return self.connector(tid, id)

    # Jobs follow the billing queue: read outside locks, then fence the commit with the lease token.

    @staticmethod
    def _job(row):
        if not row:
            return None
        return dict(id=str(row[0]), status=row[1], payload=decode(row[2]), created_at=str(row[3]), updated_at=str(row[4]),
                    poll_url='/api/v1/observability/sync-jobs/' + str(row[0]))

    def job(self, tid, id):
        with self.store.transaction(tid) as db:
            return self._job(db.execute('SELECT id,state,payload,created_at,updated_at FROM observability_jobs WHERE tenant_id=%s AND id=%s',
                                        (tid, id)).fetchone())

    def submit(self, tenant, key, *, trigger='manual', connector_ids=None):
        tid, now = tenant['tenant_id'], _now().isoformat()
        selected = [c['id'] for c in self.connectors(tid, enabled_only=True) if connector_ids is None or c['id'] in connector_ids]
        if not selected:
            raise WorkflowConflict('Add or enable an observability connector first.')
        with self.store.transaction(tid, write=True) as db:
            if db.postgres:
                db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('observability-submit:' + tid,))
            prior = db.execute('SELECT id FROM observability_jobs WHERE tenant_id=%s AND request_key=%s', (tid, key)).fetchone()
            if prior:
                return self._job(db.execute('SELECT id,state,payload,created_at,updated_at FROM observability_jobs WHERE tenant_id=%s AND id=%s',
                                            (tid, prior[0])).fetchone())
            if db.execute("SELECT 1 FROM observability_jobs WHERE tenant_id=%s AND state IN ('queued','running') LIMIT 1", (tid,)).fetchone():
                raise WorkflowConflict('Another observability collection is running. Wait for it to finish.')
            id = str(uuid4())
            payload = dict(trigger=trigger, connector_ids=selected, index=0, results=[])
            db.execute("INSERT INTO observability_jobs(id,tenant_id,request_key,state,payload,created_at,updated_at) VALUES(%s,%s,%s,'queued',%s,%s,%s)",
                       (id, tid, key, db.json(payload), now, now))
        return self.job(tid, id)

    def due(self, tid, now=None):
        now = now or _now()
        latest = self.latest_snapshots(tid)
        result = []
        for connector in self.connectors(tid, enabled_only=True):
            interval = DUE_AFTER.get(connector['schedule'])
            last = latest.get(connector['id'])
            if interval and (last is None or datetime.fromisoformat(last['observed_at'].replace('Z', '+00:00')) <= now - interval):
                result.append(connector['id'])
        return result

    def claim(self, tid, *, now=None):
        now = now or _now()
        with self.store.transaction(tid, write=True) as db:
            suffix = ' FOR UPDATE SKIP LOCKED' if db.postgres else ''
            row = db.execute("SELECT id,payload,created_at FROM observability_jobs WHERE tenant_id=%s AND (state='queued' OR (state='running' AND lease_until<%s)) "
                             'ORDER BY created_at LIMIT 1' + suffix, (tid, now.isoformat())).fetchone()
            if not row:
                return None
            if datetime.fromisoformat(str(row[2]).replace('Z', '+00:00')) < now - timedelta(hours=6):
                db.execute("UPDATE observability_jobs SET state='expired',updated_at=%s WHERE tenant_id=%s AND id=%s", (now.isoformat(), tid, row[0]))
                return None
            token = str(uuid4())
            db.execute("UPDATE observability_jobs SET state='running',lease_token=%s,lease_until=%s,updated_at=%s WHERE tenant_id=%s AND id=%s",
                       (token, (now + timedelta(minutes=10)).isoformat(), now.isoformat(), tid, row[0]))
            return dict(id=str(row[0]), token=token, payload=decode(row[1]))

    def execute(self, tenant, claim, *, collect=None, refresh=None):
        from app.collectors import observability
        collect = collect or observability.collect
        tid, payload = tenant['tenant_id'], claim['payload']
        connector_id = payload['connector_ids'][payload['index']]
        connector = self.connector(tid, connector_id)
        snapshot, result = None, dict(connector_id=connector_id)
        if connector is None or not connector['enabled'] or os.getenv('CLOUDSAVER_OBSERVABILITY_SYNC', 'true') != 'true':
            result.update(status='skipped', reason='CONNECTOR_DISABLED')
        else:
            try:
                data = collect(connector, tenant)
                snapshot = ('completed', data)
                result.update(status='completed', series=len(data['series']), services=len(data['services']))
            except observability.SourceError as error:
                snapshot = ('failed', dict(error_code=error.code))
                result.update(status='failed', error_code=error.code)
            except Exception:
                snapshot = ('failed', dict(error_code='OBSERVABILITY_SOURCE_UNAVAILABLE'))
                result.update(status='failed', error_code='OBSERVABILITY_SOURCE_UNAVAILABLE')
        with self.store.transaction(tid, write=True) as db:
            suffix = ' FOR UPDATE' if db.postgres else ''
            current = db.execute('SELECT state,lease_token,lease_until FROM observability_jobs WHERE tenant_id=%s AND id=%s' + suffix, (tid, claim['id'])).fetchone()
            if not current or str(current[1]) != claim['token'] or datetime.fromisoformat(str(current[2]).replace('Z', '+00:00')) <= _now():
                raise WorkflowConflict('Observability lease was lost; no snapshot commit is permitted')
            live = refresh() if refresh else tenant
            if snapshot and (not live or not live.get('active', True) or (live.get('plan') or {}).get('access_suspended')):
                snapshot = None
                result.update(status='failed', error_code='OBSERVABILITY_WORKSPACE_INACTIVE')
            if snapshot:
                db.execute('INSERT INTO observability_snapshots(id,tenant_id,connector_id,job_id,status,payload,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                           (str(uuid4()), tid, connector_id, claim['id'], snapshot[0], db.json(snapshot[1]), _now().isoformat()))
            payload['results'].append(result)
            payload['index'] += 1
            if payload['index'] < len(payload['connector_ids']):
                state = 'queued'
            else:
                statuses = [r['status'] for r in payload['results'] if r['status'] != 'skipped']
                state = 'completed' if all(s == 'completed' for s in statuses) else 'partial' if 'completed' in statuses else 'failed'
            db.execute('UPDATE observability_jobs SET state=%s,payload=%s,updated_at=%s,lease_until=NULL,lease_token=NULL WHERE tenant_id=%s AND id=%s',
                       (state, db.json(payload), _now().isoformat(), tid, claim['id']))
        return result

    def latest_snapshots(self, tid, *, completed_only=False):
        with self.store.transaction(tid) as db:
            rows = db.execute('SELECT connector_id,status,payload,observed_at FROM observability_snapshots WHERE tenant_id=%s '
                              + ("AND status='completed' " if completed_only else '') + 'ORDER BY observed_at DESC LIMIT 500', (tid,)).fetchall()
        latest = {}
        for connector_id, status, payload, observed_at in rows:
            latest.setdefault(str(connector_id), dict(status=status, observed_at=str(observed_at), **decode(payload)))
        return latest

    def summary(self, tid):
        from app.collectors.observability import message
        latest = self.latest_snapshots(tid)
        items = []
        for connector in self.connectors(tid):
            snap = latest.get(connector['id'])
            item = dict(id=connector['id'], name=connector['name'], kind=connector['kind'], enabled=connector['enabled'], schedule=connector['schedule'],
                        status=snap['status'] if snap else 'not_collected', observed_at=snap['observed_at'] if snap else None)
            if snap and snap['status'] == 'completed':
                item.update(mapping_coverage=snap.get('mapping_coverage'), warnings=snap.get('warnings', []),
                            window_start=snap.get('window_start'), window_end=snap.get('window_end'))
            elif snap:
                item.update(error_code=snap.get('error_code'), error=message(snap.get('error_code')))
            items.append(item)
        return dict(items=items)


def attach_signals(store, tenant, rows):
    """Link the latest completed snapshots to scan rows through explicit mappings and exact resource IDs only."""
    repo = ObservabilityStore(store)
    connectors = {c['id']: c for c in repo.connectors(tenant['tenant_id'], enabled_only=True)}
    if not connectors or not rows:
        return
    wanted = {_key(r['resource_id']) for r in rows if isinstance(r.get('resource_id'), str)}
    signals = {}
    for connector_id, snap in repo.latest_snapshots(tenant['tenant_id'], completed_only=True).items():
        connector = connectors.get(connector_id)
        if not connector:
            continue
        stamp = dict(connector=connector['name'], window_start=snap.get('window_start'), window_end=snap.get('window_end'))
        for series in snap.get('series', []):
            rid = series.get('resource_id')
            if rid and _key(rid) in wanted and series.get('summary'):
                signals.setdefault(_key(rid), dict(metrics=[], services=[], thresholds=[]))['metrics'].append(
                    dict(stamp, query_id=series['query_id'], metric=series['metric'], unit=series['unit'], **series['summary']))
                signals[_key(rid)]['thresholds'].append(connector['thresholds'])
        mapping = connector['mappings'].get('service_resources', {})
        for service in snap.get('services', []):
            rid = mapping.get(service.get('service'))
            if rid and _key(rid) in wanted:
                entry = signals.setdefault(_key(rid), dict(metrics=[], services=[], thresholds=[]))
                entry['services'].append(dict(stamp, **service))
                entry['thresholds'].append(connector['thresholds'])
    for row in rows:
        found = signals.get(_key(row['resource_id'])) if isinstance(row.get('resource_id'), str) else None
        if not found:
            continue
        evidence = row.setdefault('evidence', {})
        evidence.update(_derive(found, evidence))


def _derive(found, evidence):
    latency = [s['latency_p95_ms'] for s in found['services'] if s.get('latency_p95_ms') is not None]
    latency += [m['p95'] for m in found['metrics'] if m['metric'] == 'latency_p95_ms']
    errors = [s['error_rate_pct'] for s in found['services'] if s.get('error_rate_pct') is not None]
    errors += [m['p95'] for m in found['metrics'] if m['metric'] == 'error_rate_pct']
    limit_latency = min(t['latency_p95_ms'] for t in found['thresholds'])
    limit_errors = min(t['error_rate_pct'] for t in found['thresholds'])
    reasons = []
    if latency and max(latency) > limit_latency:
        reasons.append(f'p95 latency {max(latency):,.0f} ms is above {limit_latency:,.0f} ms')
    if errors and max(errors) > limit_errors:
        reasons.append(f'error rate {max(errors):,.2f}% is above {limit_errors:,.2f}%')
    result = dict(observed_signals=dict(metrics=found['metrics'][:50], services=found['services'][:20], latency_reasons=reasons))
    if latency or errors:
        result['latency_sensitive'] = bool(reasons)
    if latency:
        result['observed_latency_p95_ms'] = round(max(latency), 2)
    if errors:
        result['observed_error_rate_pct'] = round(max(errors), 3)
    requests = [m for m in found['metrics'] if m['metric'] == 'requests_per_second']
    cost, reason = None, None
    if not requests:
        reason = 'No request-rate metric is linked to this resource.'
    elif min(m['coverage_pct'] for m in requests) < 95:
        reason = 'Request-rate coverage is below 95%.'
    elif evidence.get('billed_cost_usd') is None or evidence.get('billing_coverage') is not True:
        reason = 'Complete billed cost for the last 30 days is required.'
    else:
        daily = sum(m['avg'] for m in requests) * 86400
        if daily <= 0:
            reason = 'No requests were observed.'
        else:
            cost = round(evidence['billed_cost_usd'] / 30 / daily * 1000, 6)
    result['observed_signals'].update(cost_per_1000_requests_usd=cost, cost_per_1000_requests_reason=reason)
    return result
