import pytest

from app.collectors.event_stream import EventStreamConsumer, InMemoryEventBuffer


def test_buffer_push_and_drain():
    buffer = InMemoryEventBuffer(2)
    buffer.push({"source": "test", "id": 1})
    buffer.push({"source": "test", "id": 2})
    assert len(buffer) == 2
    drained = buffer.drain()
    assert len(drained) == 2 and len(buffer) == 0


def test_eventbridge_parse_normalizes_action():
    event = EventStreamConsumer().parse_eventbridge(
        {"detail-type": "EC2 Instance State-change Notification", "detail": {"eventName": "RunInstances", "resourceId": "i-123"}}
    )
    assert event["provider"] == "aws" and event["action"] == "RunInstances"


def test_subscribe_hooks_delegate_to_provisioner(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_INGEST_URL", "https://cloudsaver.example/api/v1/drift/cloud-events/ingest")
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setenv("CLOUDSAVER_DRIFT_EVENTBRIDGE_ROLE_ARN", "arn:aws:iam::123456789012:role/EventBridgeInvoke")
    consumer = EventStreamConsumer()

    class FakeEvents:
        def put_rule(self, **kwargs):
            return {"RuleArn": "arn:aws:events:us-east-1:123456789012:rule/cloudsaver-drift-inspect"}

        def create_connection(self, **kwargs):
            return {"ConnectionArn": "arn:aws:events:us-east-1:123456789012:connection/cloudsaver"}

        def create_api_destination(self, **kwargs):
            return {"ApiDestinationArn": "arn:aws:events:us-east-1:123456789012:destination/cloudsaver"}

        def put_targets(self, **kwargs):
            return {}

    import app.drift.cloud_event_subscriptions as subs

    monkeypatch.setattr(subs, "_aws_events_client", lambda region, factory=None: FakeEvents())
    wired = consumer.subscribe_eventbridge(account_id="123456789012")
    assert wired["provider"] == "aws"


def test_subscribe_pubsub_delegates(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_INGEST_URL", "https://cloudsaver.example/api/v1/drift/cloud-events/ingest")
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "x" * 32)

    def fake_ensure(**kwargs):
        return dict(provider="gcp", project_id=kwargs["project_id"])

    import app.drift.cloud_event_subscriptions as subs

    monkeypatch.setattr(subs, "ensure_gcp_pubsub_subscription", fake_ensure)
    wired = EventStreamConsumer().subscribe_pubsub(project_id="example-project", token_provider=lambda: "t")
    assert wired["provider"] == "gcp"
