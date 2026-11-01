"""Semantic embedding persistence helpers and pgvector backfill."""
from __future__ import annotations

from app.enterprise_store import decode
from app.semantic_embeddings_store import SemanticEmbeddingsStore

PGVECTOR_DIM = 1536


def backfill_embedding_vectors(store, tenant_id: str, *, model_id: str | None = None, batch_size: int = 500) -> dict:
    return SemanticEmbeddingsStore(store).backfill_vectors(
        tenant_id,
        model_id=model_id,
        batch_size=batch_size,
        dimensions=PGVECTOR_DIM,
    )
