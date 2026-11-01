"""CloudDriftSignal normalization and bounded outbox enqueue."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.drift.outbox_store import PlatformOutboxStore, drift_idempotency_key


class CloudDriftSignal(BaseModel):
    workspace_id: str
    provider: str
    account_or_subscription_id: str
    canonical_resource_id: str
    operation: str
    actor_principal: str
    event_timestamp_utc: str
    correlation_id: str = ""
    model_config = ConfigDict(extra="forbid")


WorkspaceResolver = Callable[[str, str], str | None]


def canonical_azure_resource_id(subject_or_scope: str) -> str:
    if not subject_or_scope or len(subject_or_scope) > 2048:
        raise ValueError("Invalid Azure resource scope")
    return subject_or_scope.lower()


def extract_azure_subscription(subject: str) -> str:
    match = re.search(
        r"/subscriptions/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        subject,
    )
    if not match:
        raise ValueError("Azure event subject missing subscription")
    return match.group(1).lower()


def extract_aws_volume_id(detail: Mapping[str, Any]) -> str | None:
    params = detail.get("requestParameters") or {}
    if not isinstance(params, dict):
        return None
    modify = params.get("ModifyVolumeRequest") or params.get("modifyVolumeRequest") or {}
    if isinstance(modify, dict) and modify.get("VolumeId"):
        return str(modify["VolumeId"])
    for key in ("volumeId", "instanceId"):
        if params.get(key):
            return str(params[key])
    return None


class InMemoryEventBuffer:
    def __init__(self, capacity: int = 1000):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._events: Deque[dict[str, Any]] = __import__("collections").deque(maxlen=capacity)

    def push(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict) or "source" not in event:
            raise ValueError("event must be a mapping with source")
        self._events.append({**event, "received_at": datetime.now(timezone.utc).isoformat()})

    def drain(self) -> list[dict[str, Any]]:
        items = list(self._events)
        self._events.clear()
        return items

    def __len__(self) -> int:
        return len(self._events)


class EventStreamConsumer:
    """Parse Azure Activity Log / AWS CloudTrail envelopes into CloudDriftSignal."""

    def __init__(self, resolve_workspace: WorkspaceResolver | None = None):
        self.resolve_workspace = resolve_workspace or (lambda _provider, account: None)

    def normalize_eventgrid(self, envelope: dict[str, Any]) -> CloudDriftSignal:
        data = envelope.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("Event Grid data must be an object")
        auth = data.get("authorization") or {}
        scope = auth.get("scope") if isinstance(auth, dict) else None
        subject = envelope.get("subject") or scope or ""
        subscription_id = extract_azure_subscription(str(subject))
        workspace_id = self.resolve_workspace("azure", subscription_id)
        if not workspace_id:
            raise ValueError("No workspace owns subscription")
        claims = data.get("claims") or {}
        actor = ""
        if isinstance(claims, dict):
            actor = str(
                claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn")
                or claims.get("appid")
                or "unknown"
            )
        operation = str(data.get("operationName") or auth.get("action") or envelope.get("eventType") or "unknown")
        timestamp = str(envelope.get("eventTime") or datetime.now(timezone.utc).isoformat())
        correlation = str(data.get("correlationId") or envelope.get("id") or "")
        return CloudDriftSignal(
            workspace_id=workspace_id,
            provider="azure",
            account_or_subscription_id=subscription_id,
            canonical_resource_id=canonical_azure_resource_id(str(scope or subject)),
            operation=operation,
            actor_principal=actor,
            event_timestamp_utc=timestamp,
            correlation_id=correlation,
        )

    def normalize_eventgrid_batch(self, batch: list[dict[str, Any]]) -> list[CloudDriftSignal]:
        if not isinstance(batch, list):
            raise ValueError("Event Grid payload must be an array")
        return [self.normalize_eventgrid(item) for item in batch]

    def normalize_eventbridge(self, envelope: dict[str, Any]) -> CloudDriftSignal:
        detail = envelope.get("detail") or {}
        if not isinstance(detail, dict):
            raise ValueError("EventBridge detail must be an object")
        if detail.get("errorCode"):
            raise ValueError("AWS API call failed; drift inspect skipped")
        operation = str(detail.get("eventName") or envelope.get("detail-type") or "unknown")
        if re.match(r"^(Describe|List|Get|Head|BatchGet)[A-Z]", operation):
            raise ValueError("Read-only AWS API call ignored")
        account = str(envelope.get("account") or detail.get("recipientAccountId") or "")
        if not re.fullmatch(r"[0-9]{12}", account):
            raise ValueError("AWS account id missing from envelope")
        workspace_id = self.resolve_workspace("aws", account)
        if not workspace_id:
            raise ValueError("No workspace owns AWS account")
        region = str(detail.get("awsRegion") or envelope.get("region") or "us-east-1")
        volume_id = extract_aws_volume_id(detail)
        if volume_id:
            canonical = f"arn:aws:ec2:{region}:{account}:volume/{volume_id}"
        else:
            canonical = f"aws:{detail.get('eventSource','unknown')}:{detail.get('eventName','unknown')}:{account}"
        identity = detail.get("userIdentity") or {}
        actor = str(identity.get("arn") or identity.get("userName") or "unknown") if isinstance(identity, dict) else "unknown"
        timestamp = str(envelope.get("time") or datetime.now(timezone.utc).isoformat())
        correlation = str(detail.get("requestID") or envelope.get("id") or "")
        return CloudDriftSignal(
            workspace_id=workspace_id,
            provider="aws",
            account_or_subscription_id=account,
            canonical_resource_id=canonical,
            operation=operation,
            actor_principal=actor,
            event_timestamp_utc=timestamp,
            correlation_id=correlation,
        )

    def normalize_gcp_audit(self, envelope: dict[str, Any]) -> CloudDriftSignal:
        proto = envelope.get("protoPayload") or envelope.get("data", {}).get("protoPayload") or {}
        if not isinstance(proto, dict):
            raise ValueError("GCP audit protoPayload must be an object")
        resource = envelope.get("resource") or {}
        labels = resource.get("labels") if isinstance(resource, dict) else {}
        project = ""
        if isinstance(labels, dict):
            project = str(labels.get("project_id") or labels.get("project") or "")
        if not project:
            project = str(envelope.get("projectId") or envelope.get("project_id") or "")
        if not project:
            raise ValueError("GCP project id missing")
        workspace_id = self.resolve_workspace("gcp", project)
        if not workspace_id:
            raise ValueError("No workspace owns GCP project")
        method = str(proto.get("methodName") or "unknown")
        resource_name = str(
            (proto.get("resourceName") if proto.get("resourceName") else None)
            or envelope.get("resourceName")
            or f"//cloudresourcemanager.googleapis.com/projects/{project}"
        )
        auth = proto.get("authenticationInfo") or {}
        actor = str(auth.get("principalEmail") or "unknown") if isinstance(auth, dict) else "unknown"
        timestamp = str(envelope.get("timestamp") or datetime.now(timezone.utc).isoformat())
        correlation = str(envelope.get("insertId") or envelope.get("id") or "")
        return CloudDriftSignal(
            workspace_id=workspace_id,
            provider="gcp",
            account_or_subscription_id=project,
            canonical_resource_id=resource_name.lower(),
            operation=method,
            actor_principal=actor,
            event_timestamp_utc=timestamp,
            correlation_id=correlation,
        )

    def parse_eventbridge(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Legacy normalized delta (kept for existing tests)."""
        detail = envelope.get("detail") or {}
        if not isinstance(detail, dict):
            raise ValueError("EventBridge detail must be an object")
        return {
            "source": "aws.eventbridge",
            "provider": "aws",
            "action": detail.get("eventName") or envelope.get("detail-type") or "unknown",
            "resource_id": detail.get("resourceId") or extract_aws_volume_id(detail),
            "raw": envelope,
        }

    def parse_eventgrid(self, envelope: dict[str, Any]) -> dict[str, Any]:
        data = envelope.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("Event Grid data must be an object")
        auth = envelope.get("data", {}).get("authorization") or {}
        scope = auth.get("scope") if isinstance(auth, dict) else None
        return {
            "source": "azure.eventgrid",
            "provider": "azure",
            "action": envelope.get("eventType") or "unknown",
            "resource_id": scope or data.get("resourceUri") or data.get("id"),
            "raw": envelope,
        }

    def parse_pubsub(self, envelope: dict[str, Any]) -> dict[str, Any]:
        asset = envelope.get("asset") or envelope.get("resource") or {}
        if not isinstance(asset, dict):
            raise ValueError("Pub/Sub asset must be an object when present")
        return {
            "source": "gcp.pubsub",
            "provider": "gcp",
            "action": envelope.get("assetType") or "unknown",
            "resource_id": asset.get("name") or asset.get("resourceName"),
            "raw": envelope,
        }

    def enqueue_drift_inspect(self, outbox: PlatformOutboxStore, signal: CloudDriftSignal) -> tuple[str, str]:
        payload = signal.model_dump()
        key = drift_idempotency_key(payload)
        return outbox.enqueue(signal.workspace_id, "DRIFT_INSPECT_RESOURCE", key, payload)

    @staticmethod
    def resource_hash(canonical_resource_id: str) -> str:
        return hashlib.sha256(canonical_resource_id.lower().encode()).hexdigest()[:16]

    def subscribe_eventbridge(self, *, account_id: str, region: str = "us-east-1") -> dict[str, Any]:
        from app.drift.cloud_event_subscriptions import ensure_aws_eventbridge_subscription

        return ensure_aws_eventbridge_subscription(account_id=account_id, region=region)

    def subscribe_eventgrid(self, *, subscription_id: str, token_provider) -> dict[str, Any]:
        from app.drift.cloud_event_subscriptions import ensure_azure_eventgrid_subscription

        return ensure_azure_eventgrid_subscription(
            subscription_id=subscription_id,
            tenant_id="",
            token_provider=token_provider,
        )

    def subscribe_pubsub(self) -> None:
        raise NotImplementedError("GCP Pub/Sub subscription wiring is not implemented in this release")
