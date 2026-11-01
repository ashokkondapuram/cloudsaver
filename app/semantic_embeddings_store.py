"""Store and retrieve semantic resource embeddings (jsonb; pgvector HNSW optional)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


class SemanticEmbeddingsStore:
    def __init__(self, store):
        self.store = store

    def upsert(self, tenant_id: str, *, cloud_resource_id: str, model_id: str, embedding: list[float], source_manifest: str | None = None) -> dict:
        if not embedding or len(embedding) > 4096:
            raise ValueError("embedding dimensions out of range")
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(tenant_id, write=True) as db:
            prior = db.execute(
                """SELECT id FROM semantic_resource_embeddings
                   WHERE tenant_id=%s AND cloud_resource_id=%s AND model_id=%s""",
                (tenant_id, cloud_resource_id, model_id),
            ).fetchone()
            if prior:
                db.execute(
                    """UPDATE semantic_resource_embeddings SET dimensions=%s,embedding=%s,source_manifest=%s,created_at=%s
                       WHERE tenant_id=%s AND id=%s""",
                    (
                        len(embedding),
                        db.json(embedding),
                        source_manifest,
                        now,
                        tenant_id,
                        str(prior[0]),
                    ),
                )
                return dict(id=str(prior[0]), updated=True)
            row_id = str(uuid4())
            db.execute(
                """INSERT INTO semantic_resource_embeddings
                   (tenant_id,id,cloud_resource_id,model_id,dimensions,embedding,source_manifest,created_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    tenant_id,
                    row_id,
                    cloud_resource_id,
                    model_id,
                    len(embedding),
                    db.json(embedding),
                    source_manifest,
                    now,
                ),
            )
        return dict(id=row_id, updated=False)
