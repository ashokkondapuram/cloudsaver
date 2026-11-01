"""GitOps AST remediation PR package and multi-VCS execution helpers."""
from __future__ import annotations

import hashlib
from typing import Any

from app.gitops_ast_hcl_indexer import block_matches_indexed_snapshot, patch_attribute_in_block


def build_pr_body(*, pillars: list[str], focus_table_md: str, policy_verdict: str) -> str:
    pillar_lines = "\n".join(f"- {item}" for item in pillars)
    return (
        "## CloudSaver GitOps remediation\n\n"
        "### Five-pillar assessment\n"
        f"{pillar_lines}\n\n"
        "### 30-day FOCUS savings\n"
        f"{focus_table_md}\n\n"
        f"**Policy check:** {policy_verdict}\n"
    )


def verify_repo_block(
    live_file: str,
    indexed_block: str,
    *,
    start_line: int,
    end_line: int,
) -> bool:
    lines = live_file.splitlines(keepends=True)
    live_block = "".join(lines[start_line - 1 : end_line])
    return block_matches_indexed_snapshot(live_block, indexed_block)


def build_remediation_package(
    mapping: dict[str, Any],
    *,
    attribute: str,
    new_token: str,
    indexed_block: str,
    live_file: str,
    branch_suffix: str,
) -> dict[str, Any]:
    if not verify_repo_block(
        live_file,
        indexed_block,
        start_line=int(mapping["start_line"]),
        end_line=int(mapping["end_line"]),
    ):
        raise ValueError("REPO_DRIFT_REINDEX_REQUIRED")
    patched = patch_attribute_in_block(
        live_file,
        start_line=int(mapping["start_line"]),
        end_line=int(mapping["end_line"]),
        attribute=attribute,
        new_value=new_token,
    )
    branch = f"cloudsaver/{branch_suffix}"
    body = build_pr_body(
        pillars=mapping.get("pillars") or ["Operational alignment verified"],
        focus_table_md=mapping.get("focus_table_md") or "| Period | Billed | Amortized |\n| --- | --- | --- |\n| 30d | — | — |",
        policy_verdict=mapping.get("policy_verdict") or "review_required",
    )
    fingerprint = hashlib.sha256(patched.encode()).hexdigest()
    return dict(
        branch=branch,
        file_path=mapping["file_path"],
        patched_content=patched,
        title=f"[CloudSaver] Remediate {mapping.get('address', 'resource')}",
        body=body,
        fingerprint=fingerprint,
        indexed_commit_sha=mapping["indexed_commit_sha"],
    )


class GitOpsPullRequestExecutor:
    """Routes remediation to the configured VCS provider (GitHub, Azure DevOps, GitLab, Bitbucket)."""

    def __init__(self, config, *, transport=None):
        self.config = config
        self.transport = transport

    def execute(self, target: dict[str, Any], package: dict[str, Any], *, file_sha: str | None = None) -> dict[str, Any]:
        from app.gitops_vcs import resolve_remediation_publisher

        publisher = resolve_remediation_publisher(target, self.config, transport=self.transport)
        return publisher.execute(target, package, file_version=file_sha)
