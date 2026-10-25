"""Tenant-owned billing runs and linked agent/IaC evidence."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.enterprise_store import decode


class WorkflowConflict(ValueError):
    pass


class WorkflowStore:
    def __init__(self, store):
        self.store = store
        if not store.url:
            with store.transaction(str(uuid4()), write=True) as db:
                for table in ('billing_sync_runs', 'agent_gitops_syncs'):
                    db.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
                        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, binding_key TEXT NOT NULL,
                        state TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, lease_until TEXT NOT NULL)''')

    def rows(self, tenant_id, table, limit=25):
        assert table in ('billing_sync_runs', 'agent_gitops_syncs')
        with self.store.transaction(tenant_id) as db:
            rows = db.execute(f'SELECT id,binding_key,state,payload,created_at,updated_at FROM {table} '
                              'WHERE tenant_id=%s ORDER BY created_at DESC,id DESC LIMIT %s', (tenant_id, limit)).fetchall()
        return [dict(id=str(r[0]), binding_key=r[1], state=r[2], payload=decode(r[3]),
                     created_at=str(r[4]), updated_at=str(r[5])) for r in rows]

    def begin(self, tenant_id, table, key, payload, *, once=False):
        assert table in ('billing_sync_runs', 'agent_gitops_syncs')
        now = datetime.now(timezone.utc)
        with self.store.transaction(tenant_id, write=True) as db:
            if db.postgres:
                db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (table+tenant_id+key,))
            prior = db.execute(f'SELECT id,state,lease_until FROM {table} WHERE tenant_id=%s AND binding_key=%s '
                               'ORDER BY created_at DESC LIMIT 1', (tenant_id, key)).fetchone()
            if prior and (once or datetime.fromisoformat(str(prior[2]).replace('Z', '+00:00')) > now):
                raise WorkflowConflict('This workflow is already recorded; inspect its status before taking another action.')
            id = str(uuid4())
            db.execute(f'INSERT INTO {table}(id,tenant_id,binding_key,state,payload,created_at,updated_at,lease_until) '
                       "VALUES(%s,%s,%s,'running',%s,%s,%s,%s)",
                       (id, tenant_id, key, db.json(payload), now.isoformat(), now.isoformat(), (now+timedelta(minutes=60 if table=='billing_sync_runs' else 15)).isoformat()))
            return id

    def finish(self, tenant_id, table, id, state, payload):
        assert table in ('billing_sync_runs', 'agent_gitops_syncs')
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            db.execute(f'UPDATE {table} SET state=%s,payload=%s,updated_at=%s,lease_until=%s WHERE tenant_id=%s AND id=%s',
                       (state, db.json(payload), now, now, tenant_id, id))
