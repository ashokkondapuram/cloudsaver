import json

import httpx
import pytest

from app.gitops import GitOpsConfig
from app.gitops_vcs import (
    VCS_AZURE_DEVOPS,
    AzureDevOpsRemediationPublisher,
    normalize_gitops_target,
    repository_label,
    resolve_remediation_publisher,
)

TENANT = "11111111-1111-4111-8111-111111111111"


def test_github_target_backward_compatible():
    row = normalize_gitops_target(
        dict(
            tenant_id=TENANT,
            target_id="infra",
            repository="example/infra",
            repository_id=123,
            base_branch="main",
            installation_id=456,
        )
    )
    assert row["vcs_provider"] == "github"
    assert repository_label(row) == "example/infra"


def test_azure_devops_target_normalizes():
    row = normalize_gitops_target(
        dict(
            tenant_id=TENANT,
            target_id="infra-ado",
            vcs_provider=VCS_AZURE_DEVOPS,
            organization="contoso",
            project="cloud-infra",
            repository="terraform",
            repository_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            base_branch="main",
        )
    )
    assert repository_label(row) == "contoso/cloud-infra/terraform"


def test_gitops_config_accepts_mixed_vcs_targets(monkeypatch):
    monkeypatch.setenv(
        "CLOUDSAVER_GITOPS_TARGETS",
        json.dumps(
            [
                dict(
                    tenant_id=TENANT,
                    target_id="gh",
                    repository="example/infra",
                    repository_id=1,
                    base_branch="main",
                    installation_id=2,
                ),
                dict(
                    tenant_id=TENANT,
                    target_id="ado",
                    vcs_provider=VCS_AZURE_DEVOPS,
                    organization="contoso",
                    project="cloud-infra",
                    repository="terraform",
                    repository_id="repo-guid",
                    base_branch="main",
                ),
            ]
        ),
    )
    monkeypatch.setenv("CLOUDSAVER_GITOPS_PUBLISH", "false")
    cfg = GitOpsConfig.load()
    assert len(cfg.targets) == 2


def test_azure_devops_publisher_creates_push_and_pr(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_AZDO_PAT", "synthetic-pat")
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, str(request.url)))
        if request.method == "GET" and "/refs?" in str(request.url):
            return httpx.Response(200, json={"value": [{"objectId": "c" * 40}]})
        if request.method == "GET" and "/items?" in str(request.url):
            return httpx.Response(200, json={"commitId": "c" * 40})
        if request.method == "POST" and str(request.url).endswith("/pushes?api-version=7.1"):
            return httpx.Response(201, json={"pushId": 9})
        if request.method == "POST" and "/pullrequests?" in str(request.url):
            return httpx.Response(201, json={"pullRequestId": 42, "url": "https://dev.azure.com/contoso/pr/42"})
        return httpx.Response(404)

    target = dict(
        vcs_provider=VCS_AZURE_DEVOPS,
        organization="contoso",
        project="cloud-infra",
        repository="terraform",
        repository_id="repo-guid",
        base_branch="main",
    )
    package = dict(
        branch="cloudsaver/rightsize",
        file_path="terraform/prod/compute.tf",
        patched_content='resource "x" {}\n',
        title="title",
        body="body",
        fingerprint="abc",
    )
    publisher = AzureDevOpsRemediationPublisher(transport=httpx.MockTransport(handler))
    result = publisher.execute(target, package, file_version="c" * 40)
    assert result["vcs_provider"] == VCS_AZURE_DEVOPS
    assert result["pr_number"] == 42
    assert any("/pushes" in url for _method, url in calls)


def test_resolve_publisher_selects_by_target_provider():
    cfg = GitOpsConfig(tuple(), False, "")
    gh = resolve_remediation_publisher(
        dict(vcs_provider="github", repository="a/b", repository_id=1, installation_id=2, base_branch="main"),
        cfg,
    )
    assert gh.__class__.__name__ == "GitHubRemediationPublisher"
    ado = resolve_remediation_publisher(dict(vcs_provider=VCS_AZURE_DEVOPS, base_branch="main"), cfg)
    assert ado.__class__.__name__ == "AzureDevOpsRemediationPublisher"
