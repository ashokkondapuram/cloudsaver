import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gitops_ast_db import load_index_from_db, sync_env_index_to_db
from app.main import create_app
from tests.test_drift_event_pipeline import AZURE_EVENT, TENANT, SUB


def test_workspace_resolver_matches_subscription():
    from app.drift.workspace_resolver import workspace_resolver_for_settings

    settings = Settings(
        "azure",
        "/tmp/unused.db",
        (
            dict(
                tenant_id=TENANT,
                name="t",
                subscription_ids=[SUB],
                api_key_sha256=hashlib.sha256(b"x" * 40).hexdigest(),
            ),
        ),
    )
    resolve = workspace_resolver_for_settings(settings)
    assert resolve("azure", SUB) == TENANT


def test_gitops_ast_db_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CLOUDSAVER_GITOPS_AST_INDEX",
        json.dumps(
            {
                "/subscriptions/x/providers/Microsoft.Compute/virtualMachines/vm": {
                    "repository": "acme/infra",
                    "file_path": "compute.tf",
                    "iac_kind": "terraform",
                    "start_line": 1,
                    "end_line": 3,
                    "indexed_commit_sha": "a" * 40,
                    "indexed_block": '  vm_size = "Standard_D4s_v5"\n',
                }
            }
        ),
    )
    settings = Settings(
        "azure",
        str(tmp_path / "ast.sqlite3"),
        (
            dict(
                tenant_id=TENANT,
                name="t",
                subscription_ids=[SUB],
                api_key_sha256=hashlib.sha256(b"k" * 40).hexdigest(),
            ),
        ),
    )
    from app.enterprise_store import EnterpriseStore

    store = EnterpriseStore(settings)
    target = dict(
        tenant_id=TENANT,
        target_id="infra",
        repository="acme/infra",
        repository_id=1,
        installation_id=2,
        base_branch="main",
    )
    result = sync_env_index_to_db(
        store,
        TENANT,
        (target,),
        __import__("app.gitops_ast_mapper", fromlist=["GitOpsAstMapper"]).GitOpsAstMapper()._index,
    )
    assert result["synced_mappings"] == 1
    index = load_index_from_db(store, TENANT)
    assert "/subscriptions/x/providers/Microsoft.Compute/virtualMachines/vm" in index


def test_drift_webhook_ingress(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "test-secret")
    settings = Settings(
        "azure",
        str(tmp_path / "drift.sqlite3"),
        (
            dict(
                tenant_id=TENANT,
                name="t",
                subscription_ids=[SUB],
                api_key_sha256=hashlib.sha256(b"k" * 40).hexdigest(),
            ),
        ),
    )
    client = TestClient(create_app(settings, scanner=lambda _: []))
    response = client.post(
        "/api/v1/drift/cloud-events/ingest",
        headers={"X-CloudSaver-Drift-Webhook-Secret": "test-secret"},
        json={"provider": "azure", "events": [AZURE_EVENT]},
    )
    assert response.status_code == 202
    assert response.json()["accepted"] == 1


def test_drift_webhook_rejects_oversized_event_batch(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "test-secret")
    settings = Settings(
        "azure",
        str(tmp_path / "drift.sqlite3"),
        (
            dict(
                tenant_id=TENANT,
                name="t",
                subscription_ids=[SUB],
                api_key_sha256=hashlib.sha256(b"k" * 40).hexdigest(),
            ),
        ),
    )
    client = TestClient(create_app(settings, scanner=lambda _: []))
    response = client.post(
        "/api/v1/drift/cloud-events/ingest",
        headers={"X-CloudSaver-Drift-Webhook-Secret": "test-secret"},
        json={"provider": "azure", "events": [AZURE_EVENT] * 101},
    )
    assert response.status_code == 422
