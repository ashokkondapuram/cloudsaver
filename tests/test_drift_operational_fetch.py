import hashlib
import json
from uuid import UUID

import httpx
import pytest

from app.config import Settings
from app.drift.operational_fetch import azure_api_version, fetch_azure_operational
from app.v3_finops_store import V3FinOpsStore


TENANT = dict(
    tenant_id="11111111-1111-4111-8111-111111111111",
    name="Ops",
    subscription_ids=["33333333-3333-4333-8333-333333333333"],
)


def test_azure_api_version_for_vm():
    rid = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    assert azure_api_version(rid) == "2022-11-01"


def test_fetch_azure_operational_parses_vm(monkeypatch):
    captured = {}

    class Credential:
        def get_token(self, scope):
            assert scope == "https://management.azure.com/.default"
            return type("Token", (), {"token": "test-token"})()

        def close(self):
            return None

    def fake_credential(_tenant, settings=None):
        return Credential()

    def fake_runtime(_tenant):
        return {}

    payload = {
        "properties": {
            "hardwareProfile": {"vmSize": "Standard_D4s_v5"},
            "tags": {"env": "prod"},
        }
    }

    class FakeReader:
        def get(self, url, params=None):
            captured["url"] = httpx.URL(url, params=params)
            return payload

        def close(self):
            return None

    monkeypatch.setattr("app.cloud_identity.azure_credential", fake_credential)
    monkeypatch.setattr("app.resource_access.runtime_settings", fake_runtime)
    monkeypatch.setattr("app.cloud_http.JSONReader", lambda **kwargs: FakeReader())

    signal = dict(
        canonical_resource_id="/subscriptions/33333333-3333-4333-8333-333333333333/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        account_or_subscription_id="33333333-3333-4333-8333-333333333333",
    )
    state = fetch_azure_operational(signal, TENANT)
    assert state["vm_size"] == "Standard_D4s_v5"
    assert state["tags"]["env"] == "prod"
    assert state["source"] == "azure_arm_live"
    assert "api-version=2022-11-01" in str(captured["url"])


def test_v3_finops_store_sqlite(tmp_path):
    settings = Settings(
        "azure",
        str(tmp_path / "v3.sqlite3"),
        (
            dict(
                tenant_id=TENANT["tenant_id"],
                name=TENANT["name"],
                subscription_ids=TENANT["subscription_ids"],
                api_key_sha256=hashlib.sha256(b"k" * 40).hexdigest(),
            ),
        ),
    )
    store = __import__("app.enterprise_store", fromlist=["EnterpriseStore"]).EnterpriseStore(settings)
    finops = V3FinOpsStore(store)
    saas = finops.insert_saas_focus_records(
        TENANT["tenant_id"],
        [
            dict(
                provider_name="snowflake",
                service_category="SaaS",
                service_subcategory="",
                resource_id="wh",
                sku_meter="",
                commitment_discount_status="Unknown",
                billed_cost_usd="1.0",
                effective_cost_usd="1.0",
                charge_period_start="2026-10-01T00:00:00Z",
                charge_period_end="2026-10-31T00:00:00Z",
                payload={"x": 1},
            )
        ],
    )
    assert saas["inserted"] == 1
    with store.transaction(TENANT["tenant_id"]) as db:
        count = db.execute("SELECT COUNT(*) FROM saas_focus_billing_records WHERE tenant_id=%s", (TENANT["tenant_id"],)).fetchone()[0]
    assert count == 1
