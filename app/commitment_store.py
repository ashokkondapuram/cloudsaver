"""Tenant-owned, append-only commitment snapshots collected by the billing worker."""
from datetime import datetime, timezone
from uuid import uuid4

from app.enterprise_store import decode


def record(db, tenant_id, provider, scope_id, job_id, status, payload):
    db.execute('INSERT INTO cloud_commitment_snapshots(id,tenant_id,provider,scope_id,job_id,status,payload,observed_at) '
               'VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
               (str(uuid4()), tenant_id, provider, scope_id, job_id, status, db.json(payload), datetime.now(timezone.utc).isoformat()))


def latest(store, tenant_id, limit=200):
    with store.transaction(tenant_id) as db:
        rows = db.execute('SELECT provider,scope_id,status,payload,observed_at FROM cloud_commitment_snapshots '
                          'WHERE tenant_id=%s ORDER BY observed_at DESC LIMIT %s', (tenant_id, limit)).fetchall()
    seen, result = set(), []
    for provider, scope_id, status, payload, observed_at in rows:
        if (provider, scope_id) in seen: continue
        seen.add((provider, scope_id))
        result.append(dict(provider=provider, scope_id=scope_id, status=status, observed_at=str(observed_at), **decode(payload)))
    return result
