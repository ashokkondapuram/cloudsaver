"""Load and query GitOps AST mappings persisted in gitops_* tables (migration 0029)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.enterprise_store import decode
from app.gitops_vcs import repository_label


def load_index_from_db(store, tenant_id: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    with store.transaction(tenant_id) as db:
        rows = db.execute(
            """SELECT m.cloud_resource_id,r.repo_url,f.file_path,f.commit_sha,m.start_line,m.end_line,
                      m.address,m.raw_attributes,m.match_tier
               FROM gitops_ast_resource_mappings m
               JOIN gitops_ast_files f ON f.tenant_id=m.tenant_id AND f.id=m.file_id
               JOIN gitops_repositories r ON r.tenant_id=m.tenant_id AND r.id=f.repository_id
               WHERE m.tenant_id=%s AND m.cloud_resource_id IS NOT NULL""",
            (tenant_id,),
        ).fetchall()
    for row in rows:
        cloud_id, repo_url, file_path, commit_sha, start, end, address, raw, tier = row
        attrs = decode(raw) if raw else {}
        if not cloud_id:
            continue
        base = dict(
            repository=repo_url,
            file_path=file_path,
            indexed_commit_sha=commit_sha,
            start_line=int(start),
            end_line=int(end),
            address=address,
            iac_kind=attrs.get("iac_kind") or "terraform",
            vcs_provider=attrs.get("vcs_provider"),
            indexed_block=attrs.get("indexed_block"),
            match_tier=tier,
        )
        for key, value in attrs.items():
            if key not in base and key not in ("iac_kind", "vcs_provider", "indexed_block"):
                base[key] = value
        index[str(cloud_id)] = base
    return index


def _ensure_repository(db, tenant_id: str, target: dict, now: str) -> str:
    repo_url = repository_label(target)
    row = db.execute(
        "SELECT id FROM gitops_repositories WHERE tenant_id=%s AND repo_url=%s",
        (tenant_id, repo_url),
    ).fetchone()
    if row:
        db.execute(
            "UPDATE gitops_repositories SET last_synced_at=%s WHERE tenant_id=%s AND id=%s",
            (now, tenant_id, str(row[0])),
        )
        return str(row[0])
    repo_id = str(uuid4())
    db.execute(
        """INSERT INTO gitops_repositories
           (tenant_id,id,repo_url,default_branch,vcs_provider,external_binding,last_synced_at)
           VALUES(%s,%s,%s,%s,%s,%s,%s)""",
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
    return repo_id


def persist_env_mapping(
    db,
    tenant_id: str,
    repository_id: str,
    cloud_resource_id: str,
    entry: dict,
    *,
    now: str,
) -> None:
    commit_sha = entry.get("indexed_commit_sha") or ("0" * 40)
    file_path = entry["file_path"]
    prior_file = db.execute(
        """SELECT id FROM gitops_ast_files
           WHERE tenant_id=%s AND repository_id=%s AND file_path=%s AND commit_sha=%s""",
        (tenant_id, repository_id, file_path, commit_sha),
    ).fetchone()
    if prior_file:
        file_id = str(prior_file[0])
    else:
        file_id = str(uuid4())
        db.execute(
            """INSERT INTO gitops_ast_files
               (tenant_id,id,repository_id,file_path,commit_sha,manifest_format,parsed_at)
               VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (
                tenant_id,
                file_id,
                repository_id,
                file_path,
                commit_sha,
                entry.get("iac_kind") or "terraform",
                now,
            ),
        )
    db.execute(
        """DELETE FROM gitops_ast_resource_mappings
           WHERE tenant_id=%s AND file_id=%s AND cloud_resource_id=%s""",
        (tenant_id, file_id, cloud_resource_id),
    )
    address = entry.get("address") or entry.get("resource_name") or cloud_resource_id
    db.execute(
        """INSERT INTO gitops_ast_resource_mappings
           (tenant_id,id,file_id,resource_type,resource_name,address,start_line,end_line,raw_attributes,
            cloud_resource_id,match_tier)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            tenant_id,
            str(uuid4()),
            file_id,
            entry.get("iac_kind") or "terraform",
            entry.get("resource_name") or address,
            address,
            int(entry["start_line"]),
            int(entry["end_line"]),
            db.json(entry),
            cloud_resource_id,
            entry.get("match_tier") or "deterministic",
        ),
    )


def sync_env_index_to_db(store, tenant_id: str, targets: tuple[dict, ...], env_index: dict[str, dict]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    allowed_repos = {repository_label(t) for t in targets if t["tenant_id"] == tenant_id}
    synced = 0
    with store.transaction(tenant_id, write=True) as db:
        repo_ids = {}
        for target in targets:
            if target["tenant_id"] != tenant_id:
                continue
            repo_ids[repository_label(target)] = _ensure_repository(db, tenant_id, target, now)
        for cloud_id, entry in env_index.items():
            repo = entry.get("repository")
            if repo not in allowed_repos:
                continue
            if not entry.get("file_path") or not entry.get("start_line") or not entry.get("end_line"):
                continue
            repository_id = repo_ids.get(repo)
            if not repository_id:
                continue
            persist_env_mapping(db, tenant_id, repository_id, cloud_id, entry, now=now)
            synced += 1
    return dict(synced_mappings=synced, synced_at=now)
