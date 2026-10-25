"""A global operator index cannot disclose foreign resources or repository bindings."""
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app
from app.store import Store
from tests.test_gitops import KEY, SUB, TARGET, TENANT, snapshot, workspace


@pytest.fixture
def mapping_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_KEY_VERIFIER", "local")
    monkeypatch.setenv("CLOUDSAVER_GITOPS_TARGETS", json.dumps([TARGET]))
    settings = Settings("azure", str(tmp_path / "mapping.db"), (workspace(),))
    scan = snapshot()
    rid = scan["findings"][0]["resource_id"]
    foreign = rid.replace(SUB, str(uuid4()))
    monkeypatch.setenv("CLOUDSAVER_GITOPS_AST_INDEX", json.dumps({
        rid: {"repository": TARGET["repository"], "file_path": "disk.tf", "iac_kind": "terraform"},
        foreign: {"repository": "other-customer/private-infra", "file_path": "secret.tf", "iac_kind": "terraform"},
    }))
    Store(settings.database).save(TENANT, scan, workspace=workspace())
    return TestClient(create_app(settings)), rid, foreign


def test_only_owned_resources_with_a_repository_grant_are_visible(mapping_api):
    api, own, foreign = mapping_api
    headers = {"Authorization": "Bearer " + KEY}
    result = api.get("/api/v1/gitops/resource-mapping", params={"resource_id": own}, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["repository"] == TARGET["repository"]
    denied = api.get("/api/v1/gitops/resource-mapping", params={"resource_id": foreign}, headers=headers)
    missing = api.get("/api/v1/gitops/resource-mapping", params={"resource_id": "not-a-resource"}, headers=headers)
    assert denied.status_code == missing.status_code == 404
    assert {k: v for k, v in denied.json().items() if k != "request_id"} == {k: v for k, v in missing.json().items() if k != "request_id"}


def test_owned_cloud_resource_does_not_grant_another_repository(mapping_api, monkeypatch):
    api, own, _ = mapping_api
    monkeypatch.setenv("CLOUDSAVER_GITOPS_AST_INDEX", json.dumps({
        own: {"repository": "other-customer/private-infra", "file_path": "secret.tf", "iac_kind": "terraform"},
    }))
    response = api.get("/api/v1/gitops/resource-mapping", params={"resource_id": own},
                       headers={"Authorization": "Bearer " + KEY})
    assert response.status_code == 404
    assert "private-infra" not in response.text


def test_mapping_lookup_requires_authentication(mapping_api):
    api, own, _ = mapping_api
    assert api.get("/api/v1/gitops/resource-mapping", params={"resource_id": own}).status_code == 401
