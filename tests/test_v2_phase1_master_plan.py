import pytest

from app.collectors.event_stream import EventStreamConsumer
from app.drift.baseline_store import baseline_hash
from app.drift.drift_manager import compare_all_operational_keys
from app.gitops_crossplane_indexer import index_manifest
from app.gitops_resource_correlation import correlate_resource


def test_baseline_hash_is_stable():
    state = {"vm_size": "Standard_D4s_v5", "etag": "abc"}
    assert baseline_hash(state) == baseline_hash(state)


def test_zero_tolerance_detects_etag_change_with_same_tags():
    baseline = {"tags": {"env": "prod"}, "etag": "1", "vm_size": "Standard_D4s_v5"}
    live = {"tags": {"env": "prod"}, "etag": "2", "vm_size": "Standard_D4s_v5"}
    result = compare_all_operational_keys(baseline, live)
    assert result.drifted and "etag_mismatch" in result.reasons


def test_aws_read_only_event_is_ignored():
    consumer = EventStreamConsumer(lambda _p, _a: "11111111-1111-4111-8111-111111111111")
    with pytest.raises(ValueError, match="Read-only"):
        consumer.normalize_eventbridge(
            {
                "account": "123456789012",
                "detail": {"eventName": "DescribeInstances", "awsRegion": "us-east-1"},
            }
        )


def test_gcp_audit_normalizes_resource():
    consumer = EventStreamConsumer(lambda _p, acct: "11111111-1111-4111-8111-111111111111" if acct == "my-project" else None)
    signal = consumer.normalize_gcp_audit(
        {
            "resource": {"labels": {"project_id": "my-project"}},
            "protoPayload": {
                "methodName": "v1.compute.instances.update",
                "resourceName": "//compute.googleapis.com/projects/my-project/zones/us-central1-a/instances/web-1",
                "authenticationInfo": {"principalEmail": "admin@example.com"},
            },
            "timestamp": "2026-10-30T22:00:00Z",
            "insertId": "abc",
        }
    )
    assert signal.provider == "gcp"
    assert "instances/web-1" in signal.canonical_resource_id


def test_crossplane_indexer_finds_xrd():
    rows = index_manifest({"apiVersion": "apiextensions.crossplane.io/v1", "kind": "CompositeResourceDefinition", "metadata": {"name": "xstorage"}})
    assert rows[0]["kind"] == "CompositeResourceDefinition"


def test_resource_correlation_prefers_deterministic_id():
    index = {"/subscriptions/x/providers/Microsoft.Compute/virtualMachines/vm": {"repository": "org/infra", "file_path": "vm.tf"}}
    hit = correlate_resource({"resource_id": "/subscriptions/x/providers/Microsoft.Compute/virtualMachines/vm"}, env_index=index)
    assert hit["tier"] == "deterministic_id"
