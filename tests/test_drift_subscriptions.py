import json

import pytest

from app.drift.cloud_event_subscriptions import ensure_aws_eventbridge_subscription, ensure_azure_eventgrid_subscription


def test_ensure_aws_eventbridge_subscription(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_INGEST_URL", "https://cloudsaver.example/api/v1/drift/cloud-events/ingest")
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "x" * 32)
    monkeypatch.setenv("CLOUDSAVER_DRIFT_EVENTBRIDGE_ROLE_ARN", "arn:aws:iam::123456789012:role/EventBridgeInvoke")

    calls = []

    class FakeEvents:
        def put_rule(self, **kwargs):
            calls.append(("put_rule", kwargs))
            return {"RuleArn": "arn:aws:events:us-east-1:123456789012:rule/cloudsaver-drift-inspect"}

        def create_connection(self, **kwargs):
            calls.append(("create_connection", kwargs))
            return {"ConnectionArn": "arn:aws:events:us-east-1:123456789012:connection/cloudsaver"}

        def create_api_destination(self, **kwargs):
            calls.append(("create_api_destination", kwargs))
            return {"ApiDestinationArn": "arn:aws:events:us-east-1:123456789012:destination/cloudsaver"}

        def put_targets(self, **kwargs):
            calls.append(("put_targets", kwargs))
            return {}

    result = ensure_aws_eventbridge_subscription(account_id="123456789012", events_client=FakeEvents())
    assert result["provider"] == "aws"
    assert any(name == "put_targets" for name, _ in calls)


def test_ensure_azure_eventgrid_subscription(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_DRIFT_INGEST_URL", "https://cloudsaver.example/api/v1/drift/cloud-events/ingest")
    monkeypatch.setenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET", "x" * 32)

    def fake_request(method, url, headers, content, timeout):
        assert method == "PUT"
        assert "Microsoft.EventGrid/eventSubscriptions" in url
        body = json.loads(content)
        assert body["properties"]["destination"]["endpointType"] == "WebHook"
        return type(
            "R",
            (),
            dict(
                status_code=201,
                json=lambda self=None: {"properties": {"provisioningState": "Succeeded"}},
            ),
        )()

    result = ensure_azure_eventgrid_subscription(
        subscription_id="00000000-0000-4000-8000-000000000001",
        tenant_id="11111111-1111-4111-8111-111111111111",
        token_provider=lambda: "token",
        requester=fake_request,
    )
    assert result["provisioning_state"] == "Succeeded"
