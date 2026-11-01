"""Transactional outbox for drift inspection and GitOps PR delivery."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.enterprise_store import decode

OUTBOX_KIND_DRIFT = "DRIFT_INSPECT_RESOURCE"
OUTBOX_KIND_GITOPS_PR = "GITOPS_CREATE_PR"
DEFAULT_LEASE_SECONDS = 120
MAX_OUTBOX_ATTEMPTS = 8


class OutboxConflict(ValueError):
    pass


class PlatformOutboxStore:
    def __init__(self, store):
        self.store = store

    def enqueue(self, tenant_id, kind, idempotency_key, payload, *, now=None):
        if kind not in (OUTBOX_KIND_DRIFT, OUTBOX_KIND_GITOPS_PR):
            raise ValueError("Unsupported outbox kind")
        if not isinstance(idempotency_key, str) or len(idempotency_key) != 64:
            raise ValueError("idempotency_key must be a 64-char hex digest")
        now = now or datetime.now(timezone.utc).isoformat()
        intent_id = str(uuid4())
        with self.store.transaction(tenant_id, write=True) as db:
            prior = db.execute(
                "SELECT id,status FROM platform_outbox_intents WHERE tenant_id=%s AND idempotency_key=%s",
                (tenant_id, idempotency_key),
            ).fetchone()
            if prior:
                return str(prior[0]), prior[1]
            db.execute(
                """INSERT INTO platform_outbox_intents
                   (tenant_id,id,kind,idempotency_key,payload,status,attempts,created_at,updated_at)
                   VALUES(%s,%s,%s,%s,%s,'pending',0,%s,%s)""",
                (tenant_id, intent_id, kind, idempotency_key, db.json(payload), now, now),
            )
        return intent_id, "pending"

    def enqueue_batch(self, tenant_id, intents):
        """Insert many outbox rows in one transaction; each item is (kind, idempotency_key, payload)."""
        if not intents:
            return []
        now = datetime.now(timezone.utc).isoformat()
        results = []
        with self.store.transaction(tenant_id, write=True) as db:
            for kind, idempotency_key, payload in intents:
                if kind not in (OUTBOX_KIND_DRIFT, OUTBOX_KIND_GITOPS_PR):
                    raise ValueError("Unsupported outbox kind")
                if not isinstance(idempotency_key, str) or len(idempotency_key) != 64:
                    raise ValueError("idempotency_key must be a 64-char hex digest")
                prior = db.execute(
                    "SELECT id,status FROM platform_outbox_intents WHERE tenant_id=%s AND idempotency_key=%s",
                    (tenant_id, idempotency_key),
                ).fetchone()
                if prior:
                    results.append((str(prior[0]), prior[1]))
                    continue
                intent_id = str(uuid4())
                db.execute(
                    """INSERT INTO platform_outbox_intents
                       (tenant_id,id,kind,idempotency_key,payload,status,attempts,created_at,updated_at)
                       VALUES(%s,%s,%s,%s,%s,'pending',0,%s,%s)""",
                    (tenant_id, intent_id, kind, idempotency_key, db.json(payload), now, now),
                )
                results.append((intent_id, "pending"))
        return results

    def _reclaim_expired(self, db, tenant_id, kind, now_iso):
        db.execute(
            """UPDATE platform_outbox_intents SET status='pending',lease_owner=NULL,lease_until=NULL,updated_at=%s
               WHERE tenant_id=%s AND kind=%s AND status='leased'
               AND (lease_until IS NULL OR lease_until<%s)""",
            (now_iso, tenant_id, kind, now_iso),
        )

    def claim_pending(self, tenant_id, kind, limit=10, *, owner=None, lease_seconds=DEFAULT_LEASE_SECONDS):
        owner = owner or secrets.token_hex(16)
        with self.store.transaction(tenant_id, write=True) as db:
            now = datetime.now(timezone.utc)
            self._reclaim_expired(db, tenant_id, kind, now.isoformat())
            rows = db.execute(
                """SELECT id,kind,idempotency_key,payload,attempts,lease_fence FROM platform_outbox_intents
                   WHERE tenant_id=%s AND kind=%s AND status='pending'
                   ORDER BY created_at,id LIMIT %s""",
                (tenant_id, kind, limit),
            ).fetchall()
            claimed = []
            for row in rows:
                now = datetime.now(timezone.utc)
                now_iso = now.isoformat()
                until_iso = (now + timedelta(seconds=lease_seconds)).isoformat()
                next_fence = int(row[5]) + 1
                changed = db.execute(
                    """UPDATE platform_outbox_intents SET status='leased',lease_owner=%s,lease_fence=%s,
                       lease_until=%s,updated_at=%s
                       WHERE tenant_id=%s AND id=%s AND status='pending'""",
                    (owner, next_fence, until_iso, now_iso, tenant_id, str(row[0])),
                ).rowcount
                if changed == 1:
                    claimed.append(
                        dict(
                            id=str(row[0]),
                            kind=row[1],
                            idempotency_key=row[2],
                            payload=decode(row[3]),
                            attempts=row[4],
                            lease_owner=owner,
                            lease_fence=next_fence,
                        )
                    )
            return claimed

    def require_lease(self, tenant_id, intent_id, lease_owner, lease_fence):
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id) as db:
            row = db.execute(
                """SELECT 1 FROM platform_outbox_intents WHERE tenant_id=%s AND id=%s AND status='leased'
                   AND lease_owner=%s AND lease_fence=%s AND lease_until IS NOT NULL AND lease_until>=%s""",
                (tenant_id, intent_id, lease_owner, lease_fence, now),
            ).fetchone()
        if not row:
            raise OutboxConflict("Outbox lease no longer valid")

    def renew_lease(
        self,
        tenant_id,
        intent_id,
        lease_owner,
        lease_fence,
        *,
        lease_seconds=DEFAULT_LEASE_SECONDS,
    ):
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        until_iso = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            changed = self._leased_update(
                db,
                tenant_id,
                intent_id,
                lease_owner=lease_owner,
                lease_fence=lease_fence,
                set_clause="lease_until=%s,updated_at=%s",
                params=(until_iso, now_iso),
                now_iso=now_iso,
            )
        if changed != 1:
            raise OutboxConflict("Outbox lease no longer valid")

    def _leased_update(self, db, tenant_id, intent_id, *, lease_owner, lease_fence, set_clause, params, now_iso):
        if not lease_owner or lease_fence is None:
            raise ValueError("lease_owner and lease_fence are required")
        return db.execute(
            f"""UPDATE platform_outbox_intents SET {set_clause}
                WHERE tenant_id=%s AND id=%s AND status='leased'
                AND lease_owner=%s AND lease_fence=%s
                AND lease_until IS NOT NULL AND lease_until>=%s""",
            (*params, tenant_id, intent_id, lease_owner, lease_fence, now_iso),
        ).rowcount

    def release_to_pending(self, tenant_id, intent_id, lease_owner, lease_fence):
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            changed = self._leased_update(
                db,
                tenant_id,
                intent_id,
                lease_owner=lease_owner,
                lease_fence=lease_fence,
                set_clause="status='pending',lease_owner=NULL,lease_until=NULL,updated_at=%s",
                params=(now,),
                now_iso=now,
            )
        if changed != 1:
            raise OutboxConflict("Outbox lease no longer valid")

    def complete(self, tenant_id, intent_id, *, lease_owner, lease_fence, result_payload=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            changed = self._leased_update(
                db,
                tenant_id,
                intent_id,
                lease_owner=lease_owner,
                lease_fence=lease_fence,
                set_clause="status='completed',lease_owner=NULL,lease_until=NULL,updated_at=%s",
                params=(now,),
                now_iso=now,
            )
        if changed != 1:
            raise OutboxConflict("Outbox lease no longer valid")

    def fail(self, tenant_id, intent_id, error_code, *, lease_owner, lease_fence, recoverable=False):
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            row = db.execute(
                """SELECT attempts FROM platform_outbox_intents WHERE tenant_id=%s AND id=%s
                   AND status='leased' AND lease_owner=%s AND lease_fence=%s
                   AND lease_until IS NOT NULL AND lease_until>=%s""",
                (tenant_id, intent_id, lease_owner, lease_fence, now),
            ).fetchone()
            if not row:
                raise OutboxConflict("Outbox lease no longer valid")
            attempts = int(row[0]) + 1
            if recoverable and attempts < MAX_OUTBOX_ATTEMPTS:
                changed = db.execute(
                    """UPDATE platform_outbox_intents SET status='pending',last_error=%s,attempts=%s,
                       lease_owner=NULL,lease_until=NULL,updated_at=%s
                       WHERE tenant_id=%s AND id=%s AND status='leased'
                       AND lease_owner=%s AND lease_fence=%s AND lease_until IS NOT NULL AND lease_until>=%s""",
                    (
                        error_code[:120],
                        attempts,
                        now,
                        tenant_id,
                        intent_id,
                        lease_owner,
                        lease_fence,
                        now,
                    ),
                ).rowcount
            else:
                changed = db.execute(
                    """UPDATE platform_outbox_intents SET status='failed',last_error=%s,attempts=%s,
                       lease_owner=NULL,lease_until=NULL,updated_at=%s
                       WHERE tenant_id=%s AND id=%s AND status='leased'
                       AND lease_owner=%s AND lease_fence=%s AND lease_until IS NOT NULL AND lease_until>=%s""",
                    (
                        error_code[:120],
                        attempts,
                        now,
                        tenant_id,
                        intent_id,
                        lease_owner,
                        lease_fence,
                        now,
                    ),
                ).rowcount
        if changed != 1:
            raise OutboxConflict("Outbox lease no longer valid")


class GitOpsRemediationStore:
    def __init__(self, store):
        self.store = store

    def queue_with_outbox(self, tenant_id, request_row, _outbox=None):
        """Insert remediation request and matching outbox intent in one transaction."""
        now = datetime.now(timezone.utc).isoformat()
        request_id = request_row["id"]
        key = request_row["idempotency_key"]
        with self.store.transaction(tenant_id, write=True) as db:
            prior = db.execute(
                "SELECT id,status FROM gitops_remediation_requests WHERE tenant_id=%s AND idempotency_key=%s",
                (tenant_id, key),
            ).fetchone()
            if prior:
                return dict(id=str(prior[0]), status=prior[1], idempotent=True)
            db.execute(
                """INSERT INTO gitops_remediation_requests
                   (tenant_id,id,idempotency_key,canonical_resource_id,status,payload,created_at,updated_at)
                   VALUES(%s,%s,%s,%s,'QUEUED',%s,%s,%s)""",
                (
                    tenant_id,
                    request_id,
                    key,
                    request_row["canonical_resource_id"],
                    db.json(request_row["payload"]),
                    now,
                    now,
                ),
            )
            db.execute(
                """INSERT INTO platform_outbox_intents
                   (tenant_id,id,kind,idempotency_key,payload,status,attempts,created_at,updated_at)
                   VALUES(%s,%s,%s,%s,%s,'pending',0,%s,%s)""",
                (
                    tenant_id,
                    str(uuid4()),
                    OUTBOX_KIND_GITOPS_PR,
                    key,
                    db.json(
                        dict(
                            remediation_request_id=request_id,
                            workspace_id=tenant_id,
                            **request_row["payload"],
                        )
                    ),
                    now,
                    now,
                ),
            )
        return dict(id=request_id, status="QUEUED", idempotent=False)

    def update_status(self, tenant_id, request_id, status, *, result=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            db.execute(
                """UPDATE gitops_remediation_requests SET status=%s,result=%s,updated_at=%s
                   WHERE tenant_id=%s AND id=%s""",
                (status, db.json(result) if result is not None else None, now, tenant_id, request_id),
            )

    def get(self, tenant_id, request_id):
        with self.store.transaction(tenant_id) as db:
            row = db.execute(
                """SELECT id,idempotency_key,canonical_resource_id,status,payload,result,created_at,updated_at
                   FROM gitops_remediation_requests WHERE tenant_id=%s AND id=%s""",
                (tenant_id, request_id),
            ).fetchone()
        if not row:
            return None
        cols = (
            "id",
            "idempotency_key",
            "canonical_resource_id",
            "status",
            "payload",
            "result",
            "created_at",
            "updated_at",
        )
        item = dict(zip(cols, row))
        item["id"] = str(item["id"])
        return item


def drift_idempotency_key(signal: dict) -> str:
    import hashlib
    import json

    material = json.dumps(
        dict(
            workspace_id=signal["workspace_id"],
            provider=signal.get("provider"),
            canonical_resource_id=signal["canonical_resource_id"],
            operation=signal["operation"],
            event_timestamp_utc=signal.get("event_timestamp_utc") or "",
            correlation_id=signal.get("correlation_id") or "",
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def gitops_pr_idempotency_key(
    workspace_id: str, canonical_resource_id: str, target_attribute_diff: str, indexed_commit_sha: str
) -> str:
    import hashlib

    material = "|".join(
        (workspace_id, canonical_resource_id.lower(), target_attribute_diff, indexed_commit_sha)
    )
    return hashlib.sha256(material.encode()).hexdigest()


def new_request_id(workspace_id: str, idempotency_key: str) -> str:
    from uuid import uuid5

    return str(uuid5(UUID(workspace_id), idempotency_key))