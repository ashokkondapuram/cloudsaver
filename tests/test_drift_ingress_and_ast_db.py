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


def _signed(tenant_id, body_bytes):
    import hmac
    import time

    from app.drift.event_ingress_api import tenant_ingest_secret

    timestamp = int(time.time())
    signature = hmac.new(tenant_ingest_secret(tenant_id).encode(), f"{timestamp}.".encode() + body_bytes, "sha256").hexdigest()
    return {"X-CloudSaver-Drift-Signature": f"t={timestamp},v1={signature}"}


def _drift_settings(tmp_path):
    return Settings(
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


def test_drift_webhook_ingress(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "test-secret-of-at-least-16-chars")
    settings = _drift_settings(tmp_path)
    client = TestClient(create_app(settings, scanner=lambda _: []))
    body = json.dumps([AZURE_EVENT]).encode()
    response = client.post(
        f"/api/v1/drift/cloud-events/ingest/{TENANT}/azure",
        headers=_signed(TENANT, body),
        content=body,
    )
    assert response.status_code == 202
    assert response.json()["accepted"] == 1


def test_drift_webhook_rejects_wrong_tenant_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "test-secret-of-at-least-16-chars")
    settings = _drift_settings(tmp_path)
    client = TestClient(create_app(settings, scanner=lambda _: []))
    body = json.dumps([AZURE_EVENT]).encode()
    other_tenant = "00000000-1111-2222-3333-444444444444"
    response = client.post(
        f"/api/v1/drift/cloud-events/ingest/{TENANT}/azure",
        headers=_signed(other_tenant, body),
        content=body,
    )
    assert response.status_code == 403


def test_drift_webhook_ignores_secret_in_body(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "test-secret-of-at-least-16-chars")
    settings = _drift_settings(tmp_path)
    client = TestClient(create_app(settings, scanner=lambda _: []))
    body = json.dumps([dict(AZURE_EVENT, webhook_secret="test-secret-of-at-least-16-chars")]).encode()
    response = client.post(f"/api/v1/drift/cloud-events/ingest/{TENANT}/azure", content=body)
    assert response.status_code == 403


def test_drift_webhook_rejects_oversized_event_batch(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "test-secret-of-at-least-16-chars")
    settings = _drift_settings(tmp_path)
    client = TestClient(create_app(settings, scanner=lambda _: []))
    body = json.dumps([AZURE_EVENT] * 101).encode()
    response = client.post(
        f"/api/v1/drift/cloud-events/ingest/{TENANT}/azure",
        headers=_signed(TENANT, body),
        content=body,
    )
    assert response.status_code == 422


def test_drift_webhook_rejects_invalid_event_without_enqueueing_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "test-secret-of-at-least-16-chars")
    settings = _drift_settings(tmp_path)
    client = TestClient(create_app(settings, scanner=lambda _: []))
    body = json.dumps([AZURE_EVENT, 42]).encode()
    response = client.post(
        f"/api/v1/drift/cloud-events/ingest/{TENANT}/azure",
        headers=_signed(TENANT, body),
        content=body,
    )
    assert response.status_code == 422
    from app.enterprise_store import EnterpriseStore

    store = EnterpriseStore(settings)
    with store.transaction(TENANT) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM platform_outbox_intents WHERE tenant_id=%s",
            (TENANT,),
        ).fetchone()[0]
    assert count == 0
