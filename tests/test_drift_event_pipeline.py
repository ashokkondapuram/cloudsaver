import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.collectors.event_stream import CloudDriftSignal, EventStreamConsumer
from app.drift.drift_manager import compare_operational_state
from app.drift.outbox_store import PlatformOutboxStore, drift_idempotency_key
from app.gitops_ast_hcl_indexer import patch_attribute_in_block
from app.gitops_remediation_flow import build_remediation_package, verify_repo_block
from workers.event_drift_worker import process_drift_intent


TENANT = "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
SUB = "00000000-0000-0000-0000-000000000000"


AZURE_EVENT = {
    "id": "83f79221-4c1b-4c56-b2c1-09f8a1e2d3c4",
    "subject": f"/subscriptions/{SUB}/resourceGroups/prod-rg/providers/Microsoft.Compute/virtualMachines/api-node-01",
    "eventType": "Microsoft.Resources.ResourceWriteSuccess",
    "eventTime": "2026-10-30T22:14:05.192Z",
    "data": {
        "authorization": {
            "action": "Microsoft.Compute/virtualMachines/write",
            "scope": f"/subscriptions/{SUB}/resourceGroups/prod-rg/providers/Microsoft.Compute/virtualMachines/api-node-01",
        },
        "claims": {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn": "devops-user@contoso.com",
        },
        "operationName": "Microsoft.Compute/virtualMachines/write",
        "status": "Succeeded",
    },
}


AWS_EVENT = {
    "detail-type": "AWS API Call via CloudTrail",
    "account": "123456789012",
    "time": "2026-10-30T22:15:10Z",
    "region": "us-east-1",
    "detail": {
        "eventSource": "ec2.amazonaws.com",
        "eventName": "ModifyVolume",
        "awsRegion": "us-east-1",
        "userIdentity": {"type": "AssumedRole", "arn": "arn:aws:sts::123456789012:assumed-role/AdminRole/session"},
        "requestParameters": {"ModifyVolumeRequest": {"VolumeId": "vol-0abc123def4567890", "VolumeType": "io2"}},
    },
}


def test_azure_activity_log_normalizes_to_cloud_drift_signal():
    consumer = EventStreamConsumer(resolve_workspace=lambda provider, account: TENANT if account == SUB else None)
    signal = consumer.normalize_eventgrid(AZURE_EVENT)
    assert signal.workspace_id == TENANT
    assert signal.provider == "azure"
    assert signal.canonical_resource_id.endswith("/virtualmachines/api-node-01")
    assert signal.actor_principal == "devops-user@contoso.com"


def test_aws_eventbridge_normalizes_volume_arn():
    consumer = EventStreamConsumer(resolve_workspace=lambda _p, acct: TENANT if acct == "123456789012" else None)
    signal = consumer.normalize_eventbridge(AWS_EVENT)
    assert signal.canonical_resource_id == "arn:aws:ec2:us-east-1:123456789012:volume/vol-0abc123def4567890"
    assert signal.operation == "ModifyVolume"


def test_drift_idempotency_is_stable():
    signal = CloudDriftSignal(
        workspace_id=TENANT,
        provider="azure",
        account_or_subscription_id=SUB,
        canonical_resource_id="/subscriptions/x/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm",
        operation="write",
        actor_principal="actor",
        event_timestamp_utc="2026-10-30T22:14:05.192Z",
    ).model_dump()
    assert drift_idempotency_key(signal) == drift_idempotency_key(signal)


def test_compare_operational_state_detects_vm_size_drift():
    result = compare_operational_state({"vm_size": "Standard_D8s_v5"}, {"vm_size": "Standard_D4s_v5"})
    assert result.drifted and "vm_size_mismatch" in result.reasons


def test_ast_surgical_patch_replaces_single_attribute():
    source = "resource \"azurerm_linux_virtual_machine\" \"api\" {\n  vm_size = \"Standard_D8s_v5\"\n  location = \"eastus\"\n}\n"
    patched = patch_attribute_in_block(
        source, start_line=1, end_line=3, attribute="vm_size", new_value='"Standard_D4s_v5"'
    )
    assert "Standard_D4s_v5" in patched
    assert "location" in patched


def test_repo_drift_blocks_pr_when_block_changed():
    indexed = '  vm_size = "Standard_D8s_v5"\n'
    live_file = '  vm_size = "Standard_E8s_v5"\n'
    assert not verify_repo_block(live_file, indexed, start_line=1, end_line=1)
    with pytest.raises(ValueError, match="REPO_DRIFT_REINDEX_REQUIRED"):
        build_remediation_package(
            dict(file_path="compute.tf", start_line=1, end_line=1, indexed_commit_sha="abc1234", address="vm"),
            attribute="vm_size",
            new_token='"Standard_D4s_v5"',
            indexed_block=indexed,
            live_file=live_file,
            branch_suffix="rightsize-vm",
        )


class FakeLease:
    def __init__(self):
        self.keys = set()

    def acquire(self, key, token):
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    def release(self, key, token):
        self.keys.discard(key)


class MemoryOutbox:
    def __init__(self):
        self.completed = []
        self.released = []

    def complete(self, tenant_id, intent_id, *, lease_owner=None, lease_fence=None, **kwargs):
        self.completed.append((tenant_id, intent_id, lease_owner, lease_fence))

    def fail(self, tenant_id, intent_id, code, *, lease_owner=None, lease_fence=None):
        raise AssertionError(code)

    def release_to_pending(self, tenant_id, intent_id, lease_owner, lease_fence):
        self.released.append((tenant_id, intent_id, lease_owner, lease_fence))


def test_drift_worker_skips_when_lease_busy():
    lease = FakeLease()
    outbox = MemoryOutbox()
    intent = dict(
        id=str(uuid4()),
        lease_owner="worker-a",
        lease_fence=1,
        payload=dict(
            workspace_id=TENANT,
            canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/a",
        ),
    )
    from app.collectors.event_stream import EventStreamConsumer

    resource_hash = EventStreamConsumer.resource_hash(intent["payload"]["canonical_resource_id"])
    lease.acquire(f"lease:drift_inspect:{TENANT}:{resource_hash}", "blocking")
    result = process_drift_intent(intent, outbox=outbox, lease=lease, live_reader=lambda s: {"vm_size": "x"})
    assert result["skipped"] is True
    assert outbox.completed == []
    assert outbox.released == [(TENANT, intent["id"], "worker-a", 1)]


def test_drift_worker_completes_outbox_on_match():
    lease = FakeLease()
    outbox = MemoryOutbox()
    intent = dict(
        id=str(uuid4()),
        lease_owner="worker-a",
        lease_fence=2,
        payload=dict(
            workspace_id=TENANT,
            canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/a",
        ),
    )
    result = process_drift_intent(
        intent,
        outbox=outbox,
        lease=lease,
        baseline_loader=lambda _s: {"vm_size": "Standard_D4s_v5"},
        live_reader=lambda _s: {"vm_size": "Standard_D4s_v5"},
    )
    assert result["drifted"] is False
    assert outbox.completed == [(TENANT, intent["id"], "worker-a", 2)]


def test_platform_outbox_lease_recovery_and_fencing(tmp_path):
    import hashlib

    from app.config import Settings
    from app.enterprise_store import EnterpriseStore
    from app.drift.outbox_store import OUTBOX_KIND_DRIFT, OutboxConflict, PlatformOutboxStore

    settings = Settings(
        "azure",
        str(tmp_path / "outbox.sqlite3"),
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
    outbox = PlatformOutboxStore(store)
    key = hashlib.sha256(b"drift-intent").hexdigest()
    intent_id, status = outbox.enqueue(
        TENANT,
        OUTBOX_KIND_DRIFT,
        key,
        dict(workspace_id=TENANT, canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/a"),
    )
    assert status == "pending"
    first = outbox.claim_pending(TENANT, OUTBOX_KIND_DRIFT, owner="worker-one")
    assert len(first) == 1 and first[0]["id"] == intent_id
    stale = first[0]
    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with store.transaction(TENANT, write=True) as db:
        db.execute(
            "UPDATE platform_outbox_intents SET lease_until=%s WHERE tenant_id=%s AND id=%s",
            (expired, TENANT, intent_id),
        )
    reclaimed = outbox.claim_pending(TENANT, OUTBOX_KIND_DRIFT, owner="worker-two")
    assert len(reclaimed) == 1
    assert reclaimed[0]["lease_fence"] > stale["lease_fence"]
    with pytest.raises(OutboxConflict):
        outbox.complete(
            TENANT,
            intent_id,
            lease_owner=stale["lease_owner"],
            lease_fence=stale["lease_fence"],
        )
    outbox.complete(
        TENANT,
        intent_id,
        lease_owner=reclaimed[0]["lease_owner"],
        lease_fence=reclaimed[0]["lease_fence"],
    )
