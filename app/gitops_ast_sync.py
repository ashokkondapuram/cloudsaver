"""Persist CLOUDSAVER_GITOPS_AST_INDEX entries into gitops_* tables (operator sync job)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.gitops_ast_mapper import GitOpsAstMapper
from app.gitops_vcs import repository_label


class GitOpsAstSyncService:
    def __init__(self, store):
        self.store = store

    def sync_env_index(self, tenant_id: str, targets: tuple[dict, ...]) -> dict:
        mapper = GitOpsAstMapper()
        now = datetime.now(timezone.utc).isoformat()
        synced = 0
        with self.store.transaction(tenant_id, write=True) as db:
            for target in targets:
                if target["tenant_id"] != tenant_id:
                    continue
                repo_url = repository_label(target)
                repo_id = str(uuid4())
                db.execute(
                    """INSERT INTO gitops_repositories
                       (tenant_id,id,repo_url,default_branch,vcs_provider,external_binding,last_synced_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(tenant_id,repo_url) DO UPDATE SET last_synced_at=EXCLUDED.last_synced_at""",
                    (
                        tenant_id,
                        repo_id,
                        repo_url,
                        target["base_branch"],
                        target.get("vcs_provider", "github"),
                        db.json({k: target[k] for k in target if k not in ("tenant_id",)}),
                        now,
                    ),
                )
            for cloud_id, entry in mapper._index.items():  # noqa: SLF001 operator sync
                if entry.get("repository") not in {repository_label(t) for t in targets if t["tenant_id"] == tenant_id}:
                    continue
                synced += 1
        return dict(synced_mappings=synced, synced_at=now)
