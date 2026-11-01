"""Multi-provider Git remediation publishers (GitHub, Azure DevOps, GitLab, Bitbucket)."""
from __future__ import annotations

import base64
import os
import re
import time
from typing import Any
from uuid import UUID

import httpx

from app.gitops import GitOpsFailure, GitOpsUnavailable

VCS_GITHUB = "github"
VCS_AZURE_DEVOPS = "azure_devops"
VCS_GITLAB = "gitlab"
VCS_BITBUCKET = "bitbucket"
SUPPORTED_VCS = (VCS_GITHUB, VCS_AZURE_DEVOPS, VCS_GITLAB, VCS_BITBUCKET)

_GITHUB_TARGET_KEYS = frozenset(
    {"target_id", "tenant_id", "repository", "repository_id", "base_branch", "installation_id"}
)
_AZDO_TARGET_KEYS = frozenset(
    {"target_id", "tenant_id", "organization", "project", "repository", "repository_id", "base_branch", "vcs_provider"}
)
_GITLAB_TARGET_KEYS = frozenset(
    {"target_id", "tenant_id", "project_path", "project_id", "base_branch", "vcs_provider", "gitlab_host"}
)
_BITBUCKET_TARGET_KEYS = frozenset(
    {"target_id", "tenant_id", "workspace", "repository_slug", "repository_id", "base_branch", "vcs_provider"}
)


def repository_label(target: dict[str, Any]) -> str:
    provider = target.get("vcs_provider", VCS_GITHUB)
    if provider == VCS_GITHUB:
        return target["repository"]
    if provider == VCS_AZURE_DEVOPS:
        return f"{target['organization']}/{target['project']}/{target['repository']}"
    if provider == VCS_GITLAB:
        return target["project_path"]
    if provider == VCS_BITBUCKET:
        return f"{target['workspace']}/{target['repository_slug']}"
    raise ValueError("Unsupported VCS provider")


def normalize_gitops_target(target: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(target, dict):
        raise ValueError("GitOps target must be an object")
    provider = target.get("vcs_provider", VCS_GITHUB)
    if provider not in SUPPORTED_VCS:
        raise ValueError("Unsupported vcs_provider")
    keys = set(target)
    if provider == VCS_GITHUB:
        if keys not in (_GITHUB_TARGET_KEYS, _GITHUB_TARGET_KEYS | {"vcs_provider"}):
            raise ValueError("GitOps targets require explicit repository and installation bindings")
        row = dict(target, tenant_id=str(UUID(target["tenant_id"])), vcs_provider=VCS_GITHUB)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", row["target_id"]) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}/[A-Za-z0-9_.-]{1,100}", row["repository"]
        ):
            raise ValueError("Invalid GitOps target/repository name")
        if row["repository"].split("/")[1] in (".", ".."):
            raise ValueError("Invalid GitOps repository path")
        if any(type(row[k]) is not int or not 1 <= row[k] < 2**53 for k in ("repository_id", "installation_id")):
            raise ValueError("Numeric repository and installation IDs are required")
    elif provider == VCS_AZURE_DEVOPS:
        if keys != _AZDO_TARGET_KEYS:
            raise ValueError("Azure DevOps targets require organization, project, repository and repository_id")
        row = dict(target, tenant_id=str(UUID(target["tenant_id"])))
        for field in ("organization", "project", "repository"):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", row[field]):
                raise ValueError("Invalid Azure DevOps repository coordinates")
        if not isinstance(row["repository_id"], str) or not row["repository_id"]:
            raise ValueError("Azure DevOps repository_id is required")
    elif provider == VCS_GITLAB:
        if keys not in (_GITLAB_TARGET_KEYS, _GITLAB_TARGET_KEYS - {"gitlab_host"}):
            raise ValueError("GitLab targets require project_path and project_id")
        row = dict(
            target,
            tenant_id=str(UUID(target["tenant_id"])),
            gitlab_host=target.get("gitlab_host") or "https://gitlab.com",
        )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+", row["project_path"]):
            raise ValueError("Invalid GitLab project_path")
        if type(row["project_id"]) is not int or not 1 <= row["project_id"] < 2**53:
            raise ValueError("GitLab project_id must be numeric")
    else:
        if keys != _BITBUCKET_TARGET_KEYS:
            raise ValueError("Bitbucket targets require workspace, repository_slug and repository_id")
        row = dict(target, tenant_id=str(UUID(target["tenant_id"])))
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", row["workspace"]):
            raise ValueError("Invalid Bitbucket workspace")
        if not re.fullmatch(r"[a-z0-9._-]{1,100}", row["repository_slug"]):
            raise ValueError("Invalid Bitbucket repository slug")
        if not isinstance(row["repository_id"], str) or not row["repository_id"]:
            raise ValueError("Bitbucket repository_id is required")

    branch = row["base_branch"]
    if (
        not isinstance(branch, str)
        or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,119}", branch)
        or any(x in branch for x in ("..", "//", "@{"))
        or branch.endswith(("/", ".", ".lock"))
    ):
        raise ValueError("Invalid GitOps base branch")
    return row


def validate_publish_credentials(targets: tuple[dict[str, Any], ...], *, enabled: bool, app_id: str) -> None:
    if not enabled:
        return
    providers = {t.get("vcs_provider", VCS_GITHUB) for t in targets}
    if VCS_GITHUB in providers and (not app_id.isdigit() or not os.getenv("CLOUDSAVER_GITHUB_APP_PRIVATE_KEY")):
        raise ValueError("GitHub App configuration is required for GitHub targets")
    if VCS_AZURE_DEVOPS in providers and not os.getenv("CLOUDSAVER_AZDO_PAT"):
        raise ValueError("CLOUDSAVER_AZDO_PAT is required for Azure DevOps targets")
    if VCS_GITLAB in providers and not os.getenv("CLOUDSAVER_GITLAB_TOKEN"):
        raise ValueError("CLOUDSAVER_GITLAB_TOKEN is required for GitLab targets")
    if VCS_BITBUCKET in providers and not os.getenv("CLOUDSAVER_BITBUCKET_TOKEN"):
        raise ValueError("CLOUDSAVER_BITBUCKET_TOKEN is required for Bitbucket targets")


class GitHubRemediationPublisher:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.transport = transport

    def execute(self, target: dict[str, Any], package: dict[str, Any], *, file_version: str | None) -> dict[str, Any]:
        import jwt

        if not file_version:
            raise GitOpsFailure("GitHub remediation requires base_file_sha")
        key = os.getenv("CLOUDSAVER_GITHUB_APP_PRIVATE_KEY")
        if not key:
            raise GitOpsUnavailable("GitHub App is not configured")
        now = int(time.time())
        app_token = jwt.encode(
            dict(iat=now - 60, exp=now + 540, iss=self.config.app_id), key, algorithm="RS256"
        )
        repo = "/repos/" + target["repository"]
        with httpx.Client(
            base_url="https://api.github.com",
            timeout=httpx.Timeout(30, connect=5),
            follow_redirects=False,
            transport=self.transport,
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
                    "content": base64.b64encode(package["patched_content"].encode()).decode(),
                    "branch": branch,
                    "sha": file_version,
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
                vcs_provider=VCS_GITHUB,
                pr_url=created.get("html_url"),
                pr_number=created.get("number"),
                branch=branch,
                fingerprint=package["fingerprint"],
            )


class AzureDevOpsRemediationPublisher:
    API = "7.1"

    def __init__(self, *, transport=None):
        self.transport = transport

    def _pat(self) -> str:
        token = os.getenv("CLOUDSAVER_AZDO_PAT")
        if not token:
            raise GitOpsUnavailable("Azure DevOps PAT is not configured")
        return token

    def _auth_header(self, pat: str) -> dict[str, str]:
        encoded = base64.b64encode(f":{pat}".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def execute(self, target: dict[str, Any], package: dict[str, Any], *, file_version: str | None) -> dict[str, Any]:
        org, project, repo_id = target["organization"], target["project"], target["repository_id"]
        base = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}"
        branch = package["branch"]
        path = package["file_path"]
        if not path.startswith("/"):
            path = "/" + path
        pat = self._pat()
        headers = self._auth_header(pat)
        with httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False, transport=self.transport) as client:
            def get(url, params=None):
                response = client.get(url, headers=headers, params=params or {})
                if response.status_code != 200:
                    raise GitOpsFailure("Azure DevOps read failed")
                return response.json()

            def post(url, body, *, allowed=(200, 201)):
                response = client.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    params={"api-version": self.API},
                    json=body,
                )
                if response.status_code not in allowed:
                    raise GitOpsFailure("Azure DevOps write failed")
                return response.json()

            base_ref = get(
                f"{base}/refs",
                {"filter": f"heads/{target['base_branch']}", "api-version": self.API},
            )
            values = base_ref.get("value") or []
            if not values:
                raise GitOpsFailure("Azure DevOps base branch not found")
            base_commit = values[0]["objectId"]
            if file_version and file_version != base_commit:
                item = get(
                    f"{base}/items",
                    {"path": path, "versionDescriptor.version": target["base_branch"], "api-version": self.API},
                )
                if item.get("commitId") and item["commitId"] != file_version:
                    raise GitOpsFailure("Azure DevOps file version does not match base_file_sha fence")

            push = post(
                f"{base}/pushes",
                {
                    "refUpdates": [
                        {"name": f"refs/heads/{branch}", "oldObjectId": "0000000000000000000000000000000000000000"}
                    ],
                    "commits": [
                        {
                            "comment": package["title"],
                            "changes": [
                                {
                                    "changeType": "edit",
                                    "item": {"path": path},
                                    "newContent": {
                                        "content": package["patched_content"],
                                        "contentType": "rawtext",
                                    },
                                }
                            ],
                        }
                    ],
                },
            )
            pr = post(
                f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/pullrequests",
                {
                    "sourceRefName": f"refs/heads/{branch}",
                    "targetRefName": f"refs/heads/{target['base_branch']}",
                    "title": package["title"],
                    "description": package["body"],
                },
            )
            return dict(
                vcs_provider=VCS_AZURE_DEVOPS,
                pr_url=pr.get("url") or pr.get("_links", {}).get("web", {}).get("href"),
                pr_number=pr.get("pullRequestId"),
                branch=branch,
                fingerprint=package["fingerprint"],
                push_id=push.get("pushId"),
            )


class GitLabRemediationPublisher:
    def __init__(self, *, transport=None):
        self.transport = transport

    def execute(self, target: dict[str, Any], package: dict[str, Any], *, file_version: str | None) -> dict[str, Any]:
        token = os.getenv("CLOUDSAVER_GITLAB_TOKEN")
        if not token:
            raise GitOpsUnavailable("GitLab token is not configured")
        host = target.get("gitlab_host") or "https://gitlab.com"
        project_id = target["project_id"]
        branch = package["branch"]
        headers = {"PRIVATE-TOKEN": token}
        with httpx.Client(
            base_url=host.rstrip("/") + "/api/v4",
            timeout=httpx.Timeout(30, connect=5),
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            base = client.get(f"/projects/{project_id}/repository/branches/{target['base_branch']}", headers=headers)
            if base.status_code != 200:
                raise GitOpsFailure("GitLab base branch not found")
            create = client.post(
                f"/projects/{project_id}/repository/branches",
                headers=headers,
                json={"branch": branch, "ref": target["base_branch"]},
            )
            if create.status_code not in (200, 201, 400):
                raise GitOpsFailure("GitLab branch creation failed")
            commit = client.post(
                f"/projects/{project_id}/repository/commits",
                headers=headers,
                json={
                    "branch": branch,
                    "commit_message": package["title"],
                    "actions": [
                        {
                            "action": "update",
                            "file_path": package["file_path"],
                            "content": package["patched_content"],
                            "last_commit_id": file_version,
                        }
                    ],
                },
            )
            if commit.status_code not in (200, 201):
                raise GitOpsFailure("GitLab commit failed")
            mr = client.post(
                f"/projects/{project_id}/merge_requests",
                headers=headers,
                json={
                    "source_branch": branch,
                    "target_branch": target["base_branch"],
                    "title": package["title"],
                    "description": package["body"],
                    "draft": True,
                },
            )
            if mr.status_code not in (200, 201):
                raise GitOpsFailure("GitLab merge request failed")
            body = mr.json()
            return dict(
                vcs_provider=VCS_GITLAB,
                pr_url=body.get("web_url"),
                pr_number=body.get("iid"),
                branch=branch,
                fingerprint=package["fingerprint"],
            )


class BitbucketRemediationPublisher:
    def __init__(self, *, transport=None):
        self.transport = transport

    def execute(self, target: dict[str, Any], package: dict[str, Any], *, file_version: str | None) -> dict[str, Any]:
        token = os.getenv("CLOUDSAVER_BITBUCKET_TOKEN")
        if not token:
            raise GitOpsUnavailable("Bitbucket token is not configured")
        workspace, slug = target["workspace"], target["repository_slug"]
        branch = package["branch"]
        auth = httpx.BasicAuth("x-token-auth", token)
        base_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{slug}"
        with httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False, transport=self.transport) as client:
            ref = client.get(f"{base_url}/refs/branches/{target['base_branch']}", auth=auth)
            if ref.status_code != 200:
                raise GitOpsFailure("Bitbucket base branch not found")
            target_hash = ref.json()["target"]["hash"]
            create = client.post(
                f"{base_url}/refs/branches",
                auth=auth,
                json={"name": branch, "target": {"hash": target_hash}},
            )
            if create.status_code not in (200, 201, 400):
                raise GitOpsFailure("Bitbucket branch creation failed")
            commit = client.post(
                f"{base_url}/src",
                auth=auth,
                data={
                    package["file_path"]: package["patched_content"],
                    "message": package["title"],
                    "branch": branch,
                },
            )
            if commit.status_code not in (200, 201):
                raise GitOpsFailure("Bitbucket commit failed")
            pr = client.post(
                f"{base_url}/pullrequests",
                auth=auth,
                json={
                    "title": package["title"],
                    "description": package["body"],
                    "source": {"branch": {"name": branch}},
                    "destination": {"branch": {"name": target["base_branch"]}},
                    "close_source_branch": False,
                },
            )
            if pr.status_code not in (200, 201):
                raise GitOpsFailure("Bitbucket pull request failed")
            body = pr.json()
            return dict(
                vcs_provider=VCS_BITBUCKET,
                pr_url=body.get("links", {}).get("html", {}).get("href"),
                pr_number=body.get("id"),
                branch=branch,
                fingerprint=package["fingerprint"],
            )


def resolve_remediation_publisher(target: dict[str, Any], config, *, transport=None):
    provider = target.get("vcs_provider", VCS_GITHUB)
    if provider == VCS_GITHUB:
        return GitHubRemediationPublisher(config, transport=transport)
    if provider == VCS_AZURE_DEVOPS:
        return AzureDevOpsRemediationPublisher(transport=transport)
    if provider == VCS_GITLAB:
        return GitLabRemediationPublisher(transport=transport)
    if provider == VCS_BITBUCKET:
        return BitbucketRemediationPublisher(transport=transport)
    raise GitOpsFailure("Unsupported VCS provider")


def fetch_repository_text_file(
    target: dict[str, Any],
    path: str,
    ref: str,
    config,
    *,
    transport=None,
) -> str:
    """Read a single text file at ref for remediation drift checks."""
    from urllib.parse import quote

    provider = target.get("vcs_provider", VCS_GITHUB)
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise GitOpsFailure("Invalid repository file path")
    if provider == VCS_GITHUB:
        import jwt

        key = os.getenv("CLOUDSAVER_GITHUB_APP_PRIVATE_KEY")
        if not key:
            raise GitOpsUnavailable("GitHub App is not configured")
        now = int(time.time())
        app_token = jwt.encode(
            dict(iat=now - 60, exp=now + 540, iss=config.app_id), key, algorithm="RS256"
        )
        repo = "/repos/" + target["repository"]
        with httpx.Client(
            base_url="https://api.github.com",
            timeout=httpx.Timeout(30, connect=5),
            follow_redirects=False,
            transport=transport,
        ) as client:

            def request(method, api_path, token, *, allowed=(200, 201)):
                response = client.request(
                    method,
                    api_path,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                if response.status_code not in allowed:
                    raise GitOpsFailure("GitHub rejected file read")
                return response.json() if response.content else None

            access = request(
                "POST",
                f"/app/installations/{target['installation_id']}/access_tokens",
                app_token,
            )
            token = access["token"]
            blob = request(
                "GET",
                repo + "/contents/" + quote(path, safe="/") + "?ref=" + quote(ref, safe=""),
                token,
            )
            if blob.get("type") != "file" or blob.get("encoding") != "base64":
                raise GitOpsFailure("GitHub file content is unavailable")
            return base64.b64decode(blob["content"]).decode()

    if provider == VCS_AZURE_DEVOPS:
        org, project, repo_id = target["organization"], target["project"], target["repository_id"]
        api_path = f"/{path.lstrip('/')}"
        base = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/items"
        pat = os.getenv("CLOUDSAVER_AZDO_PAT")
        if not pat:
            raise GitOpsUnavailable("Azure DevOps PAT is not configured")
        headers = {"Authorization": "Basic " + base64.b64encode(f":{pat}".encode()).decode()}
        with httpx.Client(timeout=httpx.Timeout(30, connect=5), transport=transport) as client:
            response = client.get(
                base,
                params={"path": api_path, "versionDescriptor.version": ref, "versionDescriptor.versionType": "commit", "$format": "text"},
                headers=headers,
            )
            if response.status_code != 200:
                raise GitOpsFailure("Azure DevOps file read failed")
            return response.text

    if provider == VCS_GITLAB:
        token = os.getenv("CLOUDSAVER_GITLAB_TOKEN")
        if not token:
            raise GitOpsUnavailable("GitLab token is not configured")
        host = target.get("gitlab_host") or "https://gitlab.com"
        project_id = target["project_id"]
        encoded_path = quote(path, safe="")
        with httpx.Client(timeout=httpx.Timeout(30, connect=5), transport=transport) as client:
            response = client.get(
                f"{host}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw",
                params={"ref": ref},
                headers={"PRIVATE-TOKEN": token},
            )
            if response.status_code != 200:
                raise GitOpsFailure("GitLab file read failed")
            return response.text

    if provider == VCS_BITBUCKET:
        token = os.getenv("CLOUDSAVER_BITBUCKET_TOKEN")
        if not token:
            raise GitOpsUnavailable("Bitbucket token is not configured")
        workspace, slug = target["workspace"], target["repository_slug"]
        auth = httpx.BasicAuth("x-token-auth", token)
        with httpx.Client(timeout=httpx.Timeout(30, connect=5), transport=transport) as client:
            response = client.get(
                f"https://api.bitbucket.org/2.0/repositories/{workspace}/{slug}/src/{ref}/{path.lstrip('/')}",
                auth=auth,
            )
            if response.status_code != 200:
                raise GitOpsFailure("Bitbucket file read failed")
            return response.text

    raise GitOpsFailure("Unsupported VCS provider")
