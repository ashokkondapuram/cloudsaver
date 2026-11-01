"""GitHub App repository indexer: fetch .tf files at branch HEAD and persist AST mappings."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.gitops_ast_db import _ensure_repository, persist_env_mapping
from app.gitops_terraform_ast_indexer import index_terraform_file
from app.gitops_vcs import (
    VCS_GITHUB,
    fetch_repository_text_file,
    github_list_terraform_paths,
    github_resolve_branch_sha,
    repository_label,
)


def scope_hints_for_tenant(tenant_row: dict[str, Any]) -> dict[str, Any]:
    subscriptions = tenant_row.get("subscription_ids") or []
    accounts = tenant_row.get("aws_accounts") or []
    projects = tenant_row.get("gcp_projects") or []
    return dict(
        azure_subscription_id=str(subscriptions[0]).lower() if subscriptions else None,
        aws_account_id=str(accounts[0]) if accounts else None,
        aws_region="us-east-1",
        gcp_project_id=str(projects[0]) if projects else None,
        gcp_zone="us-central1-a",
    )


def index_github_target(
    store,
    tenant_id: str,
    target: dict[str, Any],
    config,
    *,
    tenant_row: dict[str, Any],
    transport=None,
    max_files: int = 200,
) -> dict[str, Any]:
    if target.get("vcs_provider", VCS_GITHUB) != VCS_GITHUB:
        raise ValueError("Repository AST indexing is implemented for GitHub targets in this release")
    commit_sha = github_resolve_branch_sha(target, config, transport=transport)
    paths = github_list_terraform_paths(target, config, commit_sha, transport=transport, limit=max_files)
    scope = scope_hints_for_tenant(tenant_row)
    repo = repository_label(target)
    now = datetime.now(timezone.utc).isoformat()
    indexed = 0
    with store.transaction(tenant_id, write=True) as db:
        repository_id = _ensure_repository(db, tenant_id, target, now)
        for path in paths:
            source = fetch_repository_text_file(target, path, commit_sha, config, transport=transport)
            for row in index_terraform_file(file_path=path, source=source, scope=scope):
                entry = dict(row, repository=repo, indexed_commit_sha=commit_sha, vcs_provider=VCS_GITHUB)
                persist_env_mapping(
                    db,
                    tenant_id,
                    repository_id,
                    row["cloud_resource_id"],
                    entry,
                    now=now,
                )
                indexed += 1
    return dict(
        repository=repo,
        commit_sha=commit_sha,
        terraform_files=len(paths),
        indexed_mappings=indexed,
        indexed_at=now,
    )
