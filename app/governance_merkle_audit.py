"""Append-only SHA-256 Merkle audit chain (v3 scaffold)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


GENESIS = "0" * 64


def chain_hash(previous: str, payload_digest: str, *, tenant_id: str, category: str, actor: str, recorded_at: str) -> str:
    material = json.dumps(
        dict(
            tenant_id=tenant_id,
            category=category,
            actor=actor,
            payload_digest=payload_digest,
            previous=previous,
            recorded_at=recorded_at,
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


class MerkleAuditChain:
    def __init__(self, store):
        self.store = store

    def append(self, tenant_id: str, *, category: str, actor: str, payload: dict) -> dict:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            row = db.execute(
                """SELECT entry_chain_hash FROM tamper_evident_audit_chain
                   WHERE tenant_id=%s ORDER BY sequence_id DESC LIMIT 1""",
                (tenant_id,),
            ).fetchone()
            previous = row[0] if row else GENESIS
            entry = chain_hash(previous, digest, tenant_id=tenant_id, category=category, actor=actor, recorded_at=now)
            db.execute(
                """INSERT INTO tamper_evident_audit_chain
                   (tenant_id,event_category,actor_identity,payload_digest_sha256,
                    previous_chain_hash,entry_chain_hash,recorded_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (tenant_id, category, actor, digest, previous, entry, now),
            )
        return dict(payload_digest_sha256=digest, previous_chain_hash=previous, entry_chain_hash=entry)
