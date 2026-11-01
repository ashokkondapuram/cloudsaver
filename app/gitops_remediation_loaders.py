"""Default VCS file loaders for GitOps remediation outbox delivery."""
from __future__ import annotations

from app.gitops_vcs import fetch_repository_text_file


def default_indexed_block_loader():
    def load(mapping: dict) -> str:
        block = mapping.get("indexed_block")
        if isinstance(block, str) and block:
            return block
        live = mapping.get("_live_file")
        start, end = mapping.get("start_line"), mapping.get("end_line")
        if live and start and end:
            lines = live.splitlines(keepends=True)
            return "".join(lines[int(start) - 1 : int(end)])
        raise ValueError("indexed_block missing from AST mapping; reindex required")

    return load


def default_file_loader(config, *, transport=None):
    def load(target: dict, mapping: dict) -> str:
        path = mapping["file_path"]
        ref = mapping.get("indexed_commit_sha") or target["base_branch"]
        return fetch_repository_text_file(target, path, ref, config, transport=transport)

    return load


def gitops_delivery_kwargs(store, tenant_id: str, *, transport=None) -> dict | None:
    from app.drift.outbox_store import GitOpsRemediationStore
    from app.gitops import GitOpsConfig
    from app.gitops_ast_mapper import GitOpsAstMapper
    from app.gitops_remediation_flow import GitOpsPullRequestExecutor

    try:
        config = GitOpsConfig.load()
    except ValueError:
        return None
    if not config.enabled:
        return None
    return dict(
        remediation_store=GitOpsRemediationStore(store),
        github_executor=GitOpsPullRequestExecutor(config, transport=transport),
        config=config,
        file_loader=default_file_loader(config, transport=transport),
        indexed_block_loader=default_indexed_block_loader(),
        mapper=GitOpsAstMapper.for_tenant(store, tenant_id),
    )
