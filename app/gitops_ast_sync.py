"""Persist CLOUDSAVER_GITOPS_AST_INDEX entries into gitops_* tables (operator sync job)."""
from __future__ import annotations

from app.gitops_ast_db import load_index_from_db, sync_env_index_to_db
from app.gitops_ast_mapper import GitOpsAstMapper


class GitOpsAstSyncService:
    def __init__(self, store):
        self.store = store

    def sync_env_index(self, tenant_id: str, targets: tuple[dict, ...]) -> dict:
        mapper = GitOpsAstMapper()
        return sync_env_index_to_db(self.store, tenant_id, targets, mapper._index)  # noqa: SLF001

    def load_merged_index(self, tenant_id: str) -> dict[str, dict]:
        env = GitOpsAstMapper()._index  # noqa: SLF001
        db_index = load_index_from_db(self.store, tenant_id)
        merged = dict(db_index)
        merged.update(env)
        return merged
