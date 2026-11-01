import hashlib

from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.semantic_embeddings_pipeline import backfill_embedding_vectors
from app.semantic_embeddings_store import SemanticEmbeddingsStore


TENANT = "11111111-1111-4111-8111-111111111111"


def test_backfill_vectors_noop_without_pgvector(tmp_path):
    settings = Settings(
        "azure",
        str(tmp_path / "embed.sqlite3"),
        (
            dict(
                tenant_id=TENANT,
                name="t",
                subscription_ids=[],
                api_key_sha256=hashlib.sha256(b"k" * 40).hexdigest(),
            ),
        ),
    )
    store = EnterpriseStore(settings)
    SemanticEmbeddingsStore(store).upsert(
        TENANT,
        cloud_resource_id="/subscriptions/x/providers/Microsoft.Compute/disks/d1",
        model_id="test-model",
        embedding=[0.1] * 1536,
    )
    result = backfill_embedding_vectors(store, TENANT)
    assert result["pgvector"] is False
    assert result["updated"] == 0
