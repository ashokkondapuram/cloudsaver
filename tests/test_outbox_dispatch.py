"""Platform outbox dispatch isolation and per-intent error handling."""
import hashlib
from unittest.mock import MagicMock

from app.drift.outbox_store import OUTBOX_KIND_DRIFT, PlatformOutboxStore
from tests.test_drift_event_pipeline import TENANT
from tests.test_platform_outbox_lease import _store
from workers.event_drift_worker import dispatch_pending_drift


def test_dispatch_continues_after_one_intent_raises(tmp_path):
    store = _store(tmp_path)
    outbox = PlatformOutboxStore(store)
    for label in ("a", "b"):
        outbox.enqueue(
            TENANT,
            OUTBOX_KIND_DRIFT,
            hashlib.sha256(label.encode()).hexdigest(),
            dict(
                workspace_id=TENANT,
                canonical_resource_id=f"/subscriptions/x/providers/microsoft.compute/virtualmachines/{label}",
            ),
        )

    calls = {"n": 0}

    def flaky_live_reader(_signal):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider_read_failed")
        return {"vm_size": "Standard_D4s_v5"}

    results = dispatch_pending_drift(
        outbox,
        TENANT,
        lease=MagicMock(acquire=MagicMock(return_value=True), release=MagicMock()),
        baseline_loader=lambda _s: {"vm_size": "Standard_D4s_v5"},
        live_reader=flaky_live_reader,
    )
    assert len(results) == 2
    assert "error" in results[0]
    assert results[1].get("drifted") is False
