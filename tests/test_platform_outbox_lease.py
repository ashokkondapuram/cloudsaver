"""Platform drift/GitOps outbox lease fencing (PostgreSQL migration 0033)."""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.drift.outbox_store import OUTBOX_KIND_DRIFT, OutboxConflict, PlatformOutboxStore
from tests.test_drift_event_pipeline import TENANT, SUB


def _store(tmp_path):
    from app.config import Settings
    from app.enterprise_store import EnterpriseStore

    settings = Settings(
        "azure",
        str(tmp_path / "platform-outbox.sqlite3"),
        (
            dict(
                tenant_id=TENANT,
                name="t",
                subscription_ids=[SUB],
                api_key_sha256=hashlib.sha256(b"k" * 40).hexdigest(),
            ),
        ),
    )
    return EnterpriseStore(settings)


def test_platform_outbox_lease_recovery_and_fencing(tmp_path):
    store = _store(tmp_path)
    outbox = PlatformOutboxStore(store)
    key = hashlib.sha256(b"drift-intent").hexdigest()
    intent_id, status = outbox.enqueue(
        TENANT,
        OUTBOX_KIND_DRIFT,
        key,
        dict(
            workspace_id=TENANT,
            canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/a",
        ),
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


def test_platform_outbox_release_to_pending(tmp_path):
    store = _store(tmp_path)
    outbox = PlatformOutboxStore(store)
    key = hashlib.sha256(b"release-me").hexdigest()
    intent_id, _ = outbox.enqueue(
        TENANT,
        OUTBOX_KIND_DRIFT,
        key,
        dict(workspace_id=TENANT, canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/b"),
    )
    claimed = outbox.claim_pending(TENANT, OUTBOX_KIND_DRIFT, owner="worker-a")
    item = claimed[0]
    outbox.release_to_pending(TENANT, intent_id, item["lease_owner"], item["lease_fence"])
    with store.transaction(TENANT) as db:
        row = db.execute(
            "SELECT status,lease_owner,lease_until FROM platform_outbox_intents WHERE tenant_id=%s AND id=%s",
            (TENANT, intent_id),
        ).fetchone()
    assert row[0] == "pending" and row[1] is None and row[2] is None


def test_gitops_worker_releases_db_claim_when_redis_busy():
    from workers.delivery_worker import process_gitops_pr_intent

    class BusyLease:
        def acquire(self, key, token):
            return False

        def release(self, key, token):
            raise AssertionError("release must not run when acquire failed")

    class TrackingOutbox:
        def __init__(self):
            self.released = []

        def release_to_pending(self, tenant_id, intent_id, lease_owner, lease_fence):
            self.released.append((tenant_id, intent_id, lease_owner, lease_fence))

        def complete(self, *args, **kwargs):
            raise AssertionError("complete must not run")

        def fail(self, *args, **kwargs):
            raise AssertionError("fail must not run")

    outbox = TrackingOutbox()
    intent = dict(
        id=str(uuid4()),
        idempotency_key="a" * 64,
        lease_owner="worker-x",
        lease_fence=3,
        payload=dict(
            workspace_id=TENANT,
            remediation_request_id=str(uuid4()),
            canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/c",
            target_id="infra",
            attribute="vm_size",
            new_value_token='"Standard_D4s_v5"',
            base_file_sha="sha",
        ),
    )
    result = process_gitops_pr_intent(
        intent,
        outbox=outbox,
        remediation_store=None,
        github_executor=None,
        config=None,
        file_loader=None,
        indexed_block_loader=None,
        lease=BusyLease(),
    )
    assert result["skipped"] is True
    assert outbox.released == [(TENANT, intent["id"], "worker-x", 3)]


def test_expired_lease_cannot_complete_before_reclaim(tmp_path):
    store = _store(tmp_path)
    outbox = PlatformOutboxStore(store)
    key = hashlib.sha256(b"expired-complete").hexdigest()
    intent_id, _ = outbox.enqueue(
        TENANT,
        OUTBOX_KIND_DRIFT,
        key,
        dict(workspace_id=TENANT, canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/x"),
    )
    claimed = outbox.claim_pending(TENANT, OUTBOX_KIND_DRIFT, owner="worker-one")
    stale = claimed[0]
    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with store.transaction(TENANT, write=True) as db:
        db.execute(
            "UPDATE platform_outbox_intents SET lease_until=%s WHERE tenant_id=%s AND id=%s",
            (expired, TENANT, intent_id),
        )
    with pytest.raises(OutboxConflict):
        outbox.complete(
            TENANT,
            intent_id,
            lease_owner=stale["lease_owner"],
            lease_fence=stale["lease_fence"],
        )


def test_legacy_leased_null_expiry_is_reclaimed(tmp_path):
    store = _store(tmp_path)
    outbox = PlatformOutboxStore(store)
    key = hashlib.sha256(b"legacy-lease").hexdigest()
    intent_id, _ = outbox.enqueue(
        TENANT,
        OUTBOX_KIND_DRIFT,
        key,
        dict(workspace_id=TENANT, canonical_resource_id="/subscriptions/x/providers/microsoft.compute/virtualmachines/y"),
    )
    with store.transaction(TENANT, write=True) as db:
        db.execute(
            """UPDATE platform_outbox_intents SET status='leased',lease_owner='legacy-worker',
               lease_fence=1,lease_until=NULL WHERE tenant_id=%s AND id=%s""",
            (TENANT, intent_id),
        )
    reclaimed = outbox.claim_pending(TENANT, OUTBOX_KIND_DRIFT, owner="worker-new")
    assert len(reclaimed) == 1 and reclaimed[0]["id"] == intent_id
    assert reclaimed[0]["lease_fence"] >= 2
