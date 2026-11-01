"""Store and retrieve semantic resource embeddings (jsonb; pgvector HNSW optional)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.enterprise_store import decode


def _pgvector_column_available(db) -> bool:
    if not db.postgres:
        return False
    row = db.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_schema='public' AND table_name='semantic_resource_embeddings'
           AND column_name='embedding_vector'""",
    ).fetchone()
    return bool(row)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(item):.8g}" for item in values) + "]"


class SemanticEmbeddingsStore:
    def __init__(self, store):
        self.store = store

    def _write_vector(self, db, tenant_id: str, row_id: str, embedding: list[float], dimensions: int) -> bool:
        if not _pgvector_column_available(db) or dimensions != len(embedding):
            return False
        if dimensions != 1536:
            return False
        db.execute(
            """UPDATE semantic_resource_embeddings
               SET embedding_vector=%s::vector
               WHERE tenant_id=%s AND id=%s""",
            (_vector_literal(embedding), tenant_id, row_id),
        )
        return True

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
                row_id = str(prior[0])
                db.execute(
                    """UPDATE semantic_resource_embeddings SET dimensions=%s,embedding=%s,source_manifest=%s,created_at=%s
                       WHERE tenant_id=%s AND id=%s""",
                    (
                        len(embedding),
                        db.json(embedding),
                        source_manifest,
                        now,
                        tenant_id,
                        row_id,
                    ),
                )
                vector_synced = self._write_vector(db, tenant_id, row_id, embedding, len(embedding))
                return dict(id=row_id, updated=True, vector_synced=vector_synced)
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
            vector_synced = self._write_vector(db, tenant_id, row_id, embedding, len(embedding))
        return dict(id=row_id, updated=False, vector_synced=vector_synced)

    def backfill_vectors(self, tenant_id: str, *, model_id: str | None = None, batch_size: int = 500, dimensions: int = 1536) -> dict:
        if batch_size < 1 or batch_size > 5000:
            raise ValueError("batch_size must be between 1 and 5000")
        updated = 0
        scanned = 0
        with self.store.transaction(tenant_id, write=True) as db:
            if not _pgvector_column_available(db):
                return dict(scanned=0, updated=0, pgvector=False)
            query = """SELECT id, embedding, dimensions, model_id FROM semantic_resource_embeddings
                       WHERE tenant_id=%s AND embedding_vector IS NULL AND dimensions=%s"""
            params: list = [tenant_id, dimensions]
            if model_id:
                query += " AND model_id=%s"
                params.append(model_id)
            query += " ORDER BY created_at LIMIT %s"
            params.append(batch_size)
            rows = db.execute(query, tuple(params)).fetchall()
            for row_id, raw, dims, _model in rows:
                scanned += 1
                embedding = decode(raw)
                if not isinstance(embedding, list) or len(embedding) != dimensions:
                    continue
                if self._write_vector(db, tenant_id, str(row_id), embedding, int(dims)):
                    updated += 1
        return dict(scanned=scanned, updated=updated, pgvector=True, dimensions=dimensions)
