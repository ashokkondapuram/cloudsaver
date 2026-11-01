"""Persist resource operational baselines and append-only drift detections."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4


def baseline_hash(expected_state: dict) -> str:
    material = json.dumps(expected_state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


class BaselineStore:
    def __init__(self, store):
        self.store = store

    def upsert_baseline(self, tenant_id, canonical_resource_id, provider, expected_state: dict, *, now=None):
        now = now or datetime.now(timezone.utc).isoformat()
        digest = baseline_hash(expected_state)
        with self.store.transaction(tenant_id, write=True) as db:
            row = db.execute(
                """SELECT id FROM resource_state_baselines
                   WHERE tenant_id=%s AND canonical_resource_id=%s""",
                (tenant_id, canonical_resource_id),
            ).fetchone()
            if row:
                db.execute(
                    """UPDATE resource_state_baselines SET baseline_hash=%s,expected_state=%s,captured_at=%s
                       WHERE tenant_id=%s AND id=%s""",
                    (digest, db.json(expected_state), now, tenant_id, str(row[0])),
                )
                return digest
            db.execute(
                """INSERT INTO resource_state_baselines
                   (tenant_id,id,canonical_resource_id,provider,baseline_hash,expected_state,captured_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (tenant_id, str(uuid4()), canonical_resource_id, provider, digest, db.json(expected_state), now),
            )
        return digest

    def get_baseline(self, tenant_id, canonical_resource_id) -> dict | None:
        with self.store.transaction(tenant_id) as db:
            row = db.execute(
                """SELECT baseline_hash,expected_state,provider FROM resource_state_baselines
                   WHERE tenant_id=%s AND canonical_resource_id=%s""",
                (tenant_id, canonical_resource_id),
            ).fetchone()
        if not row:
            return None
        from app.enterprise_store import decode

        return dict(
            baseline_hash=row[0],
            expected_state=decode(row[1]),
            provider=row[2],
        )

    def record_drift_event(
        self,
        tenant_id,
        *,
        canonical_resource_id,
        provider,
        operation,
        actor_principal,
        baseline_hash_value,
        live_hash_value,
        drifted_fields,
        permit_action=None,
        ai_classification=None,
    ):
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            db.execute(
                """INSERT INTO cloud_drift_events
                   (tenant_id,id,canonical_resource_id,provider,operation,actor_principal,
                    baseline_hash,live_hash,drifted_fields,permit_action,ai_classification,detected_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    tenant_id,
                    str(uuid4()),
                    canonical_resource_id,
                    provider,
                    operation,
                    actor_principal,
                    baseline_hash_value,
                    live_hash_value,
                    db.json(drifted_fields),
                    permit_action,
                    db.json(ai_classification) if ai_classification is not None else None,
                    now,
                ),
            )
