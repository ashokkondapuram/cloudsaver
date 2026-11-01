"""GitOps AST remediation PR package and GitHub execution helpers."""
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
    """Narrow GitHub App adapter for surgical single-file remediation PRs."""

    def __init__(self, github_app, config):
        self.github_app = github_app
        self.config = config

    def execute(self, target: dict[str, Any], package: dict[str, Any], *, file_sha: str) -> dict[str, Any]:
        import os
        import time

        import httpx
        import jwt

        from app.gitops import GitOpsFailure, GitOpsUnavailable

        key = os.getenv("CLOUDSAVER_GITHUB_APP_PRIVATE_KEY")
        if not key:
            raise GitOpsUnavailable("GitHub App is not configured")
        now = int(time.time())
        app_token = jwt.encode(dict(iat=now - 60, exp=now + 540, iss=self.config.app_id), key, algorithm="RS256")
        repo = "/repos/" + target["repository"]
        with httpx.Client(
            base_url="https://api.github.com",
            timeout=httpx.Timeout(30, connect=5),
            follow_redirects=False,
        ) as client:

            def request(method, path, token, *, body=None, allowed=(200, 201)):
                response = client.request(
                    method,
                    path,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=body,
                )
                if response.status_code not in allowed:
                    raise GitOpsFailure("GitHub rejected remediation operation")
                return response.status_code, response.json() if response.content else None

            _, access = request(
                "POST",
                f"/app/installations/{target['installation_id']}/access_tokens",
                app_token,
                body={
                    "repository_ids": [target["repository_id"]],
                    "permissions": {"contents": "write", "pull_requests": "write"},
                },
            )
            token = access["token"]
            branch = package["branch"]
            _, base = request("GET", repo + "/git/ref/heads/" + target["base_branch"], token)
            base_sha = base["object"]["sha"]
            status, _ = request(
                "POST",
                repo + "/git/refs",
                token,
                body={"ref": "refs/heads/" + branch, "sha": base_sha},
                allowed=(201, 422),
            )
            if status == 422:
                _, ref = request("GET", repo + "/git/ref/heads/" + branch, token)
                if ref.get("object", {}).get("sha") != base_sha:
                    raise GitOpsFailure("Branch exists at unexpected commit")
            request(
                "PUT",
                repo + "/contents/" + package["file_path"],
                token,
                body={
                    "message": package["title"],
                    "content": __import__("base64").b64encode(package["patched_content"].encode()).decode(),
                    "branch": branch,
                    "sha": file_sha,
                },
            )
            _, created = request(
                "POST",
                repo + "/pulls",
                token,
                body={
                    "title": package["title"],
                    "body": package["body"],
                    "head": branch,
                    "base": target["base_branch"],
                    "draft": True,
                },
            )
            return dict(
                pr_url=created.get("html_url"),
                pr_number=created.get("number"),
                branch=branch,
                fingerprint=package["fingerprint"],
            )
