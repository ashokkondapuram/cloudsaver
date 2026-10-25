import json

import pytest

from app.gitops_ast_mapper import GitOpsAstMapper


RESOURCE = f"/subscriptions/22222222-2222-4222-8222-222222222222/resourceGroups/platform/providers/Microsoft.Compute/disks/archive"


def test_lookup_returns_indexed_row():
    index = {
        RESOURCE: {
            "repository": "example/infra",
            "file_path": "modules/compute/disks.tf",
            "iac_kind": "terraform",
        }
    }
    row = GitOpsAstMapper(index).lookup(RESOURCE)
    assert row.repository == "example/infra"
    assert row.iac_kind == "terraform"


def test_lookup_missing_returns_key_error():
    with pytest.raises(KeyError):
        GitOpsAstMapper({}).lookup(RESOURCE)


def test_lookup_rejects_empty_resource_id():
    with pytest.raises(ValueError):
        GitOpsAstMapper({}).lookup("")


def test_patch_preview_terraform_stub():
    mapping = GitOpsAstMapper(
        {
            RESOURCE: {
                "repository": "example/infra",
                "file_path": "modules/compute/disks.tf",
                "iac_kind": "terraform",
            }
        }
    ).lookup(RESOURCE)
    preview = GitOpsAstMapper().patch_preview(mapping, {})
    assert "import" in preview.diff


def test_patch_preview_bicep_not_implemented():
    mapping = GitOpsAstMapper(
        {
            RESOURCE: {
                "repository": "example/infra",
                "file_path": "main.bicep",
                "iac_kind": "bicep",
            }
        }
    ).lookup(RESOURCE)
    with pytest.raises(NotImplementedError):
        GitOpsAstMapper().patch_preview(mapping, {})


def test_env_index_json(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CLOUDSAVER_GITOPS_AST_INDEX",
        json.dumps(
            {
                RESOURCE: {
                    "repository": "example/infra",
                    "file_path": "disks.tf",
                    "iac_kind": "terraform",
                }
            }
        ),
    )
    assert GitOpsAstMapper().lookup(RESOURCE).file_path == "disks.tf"


def test_malformed_env_index(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_GITOPS_AST_INDEX", "{not-json")
    with pytest.raises(ValueError):
        GitOpsAstMapper()
