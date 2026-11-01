import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.gitops import GitOpsConfig
from app.gitops_github_ast_indexer import index_github_target

TENANT = "11111111-1111-4111-8111-111111111111"
SUB = "00000000-0000-4000-8000-000000000001"
SHA = "c" * 40


@pytest.fixture
def github_app_pem(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setenv("CLOUDSAVER_GITHUB_APP_PRIVATE_KEY", pem)
    return pem


def test_index_github_target_persists_tf_mapping(tmp_path, monkeypatch, github_app_pem):
    tf = '''
resource "azurerm_linux_virtual_machine" "api" {
  name                = "api-node-01"
  resource_group_name = "prod-rg"
}
'''
    monkeypatch.setenv("CLOUDSAVER_GITHUB_APP_ID", "123")
    monkeypatch.setenv(
        "CLOUDSAVER_GITOPS_TARGETS",
        json.dumps(
            [
                dict(
                    tenant_id=TENANT,
                    target_id="infra",
                    repository="acme/infra",
                    repository_id=1,
                    installation_id=99,
                    base_branch="main",
                )
            ]
        ),
    )
    config = GitOpsConfig.load()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "installation-token"})
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": SHA}})
        if f"/git/trees/{SHA}" in path:
            return httpx.Response(200, json={"tree": [{"type": "blob", "path": "compute.tf"}]})
        if path.endswith("/contents/compute.tf"):
            import base64

            return httpx.Response(
                200,
                json={"type": "file", "encoding": "base64", "content": base64.b64encode(tf.encode()).decode()},
            )
        return httpx.Response(404)

    settings = Settings(
        "azure",
        str(tmp_path / "gh-index.sqlite3"),
        (
            dict(
                tenant_id=TENANT,
                name="t",
                subscription_ids=[SUB],
                api_key_sha256=hashlib.sha256(b"k" * 40).hexdigest(),
            ),
        ),
    )
    store = EnterpriseStore(settings)
    target = config.targets[0]
    result = index_github_target(
        store,
        TENANT,
        target,
        config,
        tenant_row=settings.tenants[0],
        transport=httpx.MockTransport(handler),
    )
    assert result["indexed_mappings"] == 1
    from app.gitops_ast_db import load_index_from_db

    index = load_index_from_db(store, TENANT)
    assert any("virtualmachines/api-node-01" in key for key in index)
