"""Provision cloud-native drift event subscriptions that POST to CloudSaver ingest."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

RULE_NAME = "cloudsaver-drift-inspect"
CONNECTION_NAME = "cloudsaver-drift-ingest"
DESTINATION_NAME = "cloudsaver-drift-webhook"
AZURE_SUBSCRIPTION_NAME = "cloudsaver-drift-resource-writes"


def drift_ingest_url() -> str:
    url = (os.getenv("CLOUDSAVER_DRIFT_INGEST_URL") or "").strip()
    if not url:
        raise ValueError("CLOUDSAVER_DRIFT_INGEST_URL is required to wire cloud subscriptions")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("CLOUDSAVER_DRIFT_INGEST_URL must be an https URL")
    return url.rstrip("/")


def drift_webhook_secret() -> str:
    secret = os.getenv("CLOUDSAVER_DRIFT_WEBHOOK_SECRET") or ""
    if len(secret) < 16:
        raise ValueError("CLOUDSAVER_DRIFT_WEBHOOK_SECRET must be at least 16 characters")
    return secret


def _aws_events_client(region: str, *, factory: Callable[..., Any] | None = None):
    if factory is not None:
        return factory(region=region)
    import boto3

    return boto3.client("events", region_name=region)


def ensure_aws_eventbridge_subscription(
    *,
    account_id: str,
    region: str = "us-east-1",
    events_client=None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]{12}", account_id):
        raise ValueError("Invalid AWS account id")
    ingest = drift_ingest_url()
    secret = drift_webhook_secret()
    client = events_client or _aws_events_client(region)
    rule_arn = client.put_rule(
        Name=RULE_NAME,
        EventPattern=json.dumps(
            {
                "source": ["aws.ec2", "aws.rds"],
                "detail-type": ["AWS API Call via CloudTrail"],
                "detail": {
                    "eventName": [
                        {"prefix": "Modify"},
                        {"prefix": "Create"},
                        {"prefix": "Delete"},
                        {"prefix": "Run"},
                        {"prefix": "Start"},
                        {"prefix": "Stop"},
                    ]
                },
            }
        ),
        State="ENABLED",
        Description="Forward infrastructure mutation CloudTrail events to CloudSaver drift ingest",
    )["RuleArn"]
    connection = client.create_connection(
        Name=CONNECTION_NAME,
        AuthorizationType="API_KEY",
        AuthParameters={
            "ApiKeyAuthParameters": {
                "ApiKeyName": "X-CloudSaver-Drift-Webhook-Secret",
                "ApiKeyValue": secret,
            }
        },
    )
    destination = client.create_api_destination(
        Name=DESTINATION_NAME,
        ConnectionArn=connection["ConnectionArn"],
        InvocationEndpoint=ingest,
        HttpMethod="POST",
        InvocationRateLimitPerSecond=20,
    )
    role_arn = os.getenv("CLOUDSAVER_DRIFT_EVENTBRIDGE_ROLE_ARN")
    if not role_arn:
        raise ValueError("CLOUDSAVER_DRIFT_EVENTBRIDGE_ROLE_ARN is required for EventBridge API destinations")
    client.put_targets(
        Rule=RULE_NAME,
        Targets=[
            {
                "Id": "cloudsaver-drift-ingest",
                "Arn": destination["ApiDestinationArn"],
                "RoleArn": role_arn,
                "HttpParameters": {
                    "HeaderParameters": {
                        "X-CloudSaver-Drift-Webhook-Secret": secret,
                    }
                },
            }
        ],
    )
    return dict(
        provider="aws",
        account_id=account_id,
        region=region,
        rule_arn=rule_arn,
        connection_arn=connection["ConnectionArn"],
        destination_arn=destination["ApiDestinationArn"],
        ingest_url=ingest,
    )


def ensure_azure_eventgrid_subscription(
    *,
    subscription_id: str,
    tenant_id: str,
    token_provider: Callable[[], str],
    requester: Callable[..., httpx.Response] | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        subscription_id,
    ):
        raise ValueError("Invalid Azure subscription id")
    ingest = drift_ingest_url()
    drift_webhook_secret()
    scope = f"/subscriptions/{subscription_id.lower()}"
    api_version = "2022-06-15"
    url = (
        f"https://management.azure.com{scope}/providers/Microsoft.EventGrid/eventSubscriptions/"
        f"{AZURE_SUBSCRIPTION_NAME}?api-version={api_version}"
    )
    body = {
        "properties": {
            "destination": {
                "endpointType": "WebHook",
                "properties": {
                    "endpointUrl": ingest,
                    "maxEventsPerBatch": 10,
                    "preferredBatchSizeInKilobytes": 64,
                },
            },
            "filter": {
                "includedEventTypes": ["Microsoft.Resources.ResourceWriteSuccess"],
            },
            "eventDeliverySchema": "EventGridEvent",
            "retryPolicy": {"maxDeliveryAttempts": 30, "eventTimeToLiveInMinutes": 1440},
            "deadLetterDestination": None,
        },
    }
    headers = {
        "Authorization": "Bearer " + token_provider(),
        "Content-Type": "application/json",
    }
    request = requester or httpx.request
    response = request("PUT", url, headers=headers, content=json.dumps(body), timeout=30.0)
    if response.status_code not in (200, 201):
        raise ValueError("Azure Event Grid subscription provisioning failed")
    return dict(
        provider="azure",
        subscription_id=subscription_id.lower(),
        event_subscription=AZURE_SUBSCRIPTION_NAME,
        scope=scope,
        ingest_url=ingest,
        provisioning_state=response.json().get("properties", {}).get("provisioningState"),
    )


def ensure_workspace_subscriptions(
    tenant_row: dict[str, Any],
    *,
    azure_token: Callable[[], str] | None = None,
    aws_events_client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    results = []
    for account in tenant_row.get("aws_accounts") or []:
        region = os.getenv("CLOUDSAVER_DRIFT_AWS_REGION", "us-east-1")
        results.append(
            ensure_aws_eventbridge_subscription(
                account_id=str(account),
                region=region,
                events_client=aws_events_client_factory(region=region) if aws_events_client_factory else None,
            )
        )
    if azure_token:
        for subscription in tenant_row.get("subscription_ids") or []:
            results.append(
                ensure_azure_eventgrid_subscription(
                    subscription_id=str(subscription),
                    tenant_id=str(tenant_row["tenant_id"]),
                    token_provider=azure_token,
                )
            )
    if not results:
        raise ValueError("Workspace has no AWS accounts or Azure subscriptions to wire")
    return dict(wired=len(results), subscriptions=results)
