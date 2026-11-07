"""The optional vector index must not require privileged extension creation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import op


@pytest.mark.parametrize('installed', [False, True])
def test_semantic_migration_respects_admin_extension_provisioning(monkeypatch, installed):
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/0032_v3_semantic_embeddings.py'
    spec = importlib.util.spec_from_file_location('semantic_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    monkeypatch.setattr(op, 'execute', statements.append)
    monkeypatch.setattr(op, 'get_bind', lambda: SimpleNamespace(
        execute=lambda query: SimpleNamespace(scalar=lambda: installed)))
    module.upgrade()
    assert not any('CREATE EXTENSION' in sql for sql in statements)
    assert any('FORCE ROW LEVEL SECURITY' in sql for sql in statements)
    assert any('GRANT SELECT,INSERT,UPDATE,DELETE' in sql for sql in statements)
    assert any('vector(1536)' in sql for sql in statements) is installed
    assert any('USING hnsw' in sql for sql in statements) is installed
