"""Cloud event ingestion stubs (v2 scaffold; no live bus subscriptions)."""

from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque


class InMemoryEventBuffer:
    def __init__(self, capacity: int = 1000):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._events: Deque[dict[str, Any]] = deque(maxlen=capacity)

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
    """Parse vendor envelopes into normalized delta events."""

    def parse_eventbridge(self, envelope: dict[str, Any]) -> dict[str, Any]:
        detail = envelope.get("detail") or {}
        if not isinstance(detail, dict):
            raise ValueError("EventBridge detail must be an object")
        return {
            "source": "aws.eventbridge",
            "provider": "aws",
            "action": detail.get("eventName") or envelope.get("detail-type") or "unknown",
            "resource_id": detail.get("resourceId") or detail.get("requestParameters", {}).get("instanceId"),
            "raw": envelope,
        }

    def parse_eventgrid(self, envelope: dict[str, Any]) -> dict[str, Any]:
        data = envelope.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("Event Grid data must be an object")
        return {
            "source": "azure.eventgrid",
            "provider": "azure",
            "action": envelope.get("eventType") or "unknown",
            "resource_id": data.get("resourceUri") or data.get("id"),
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

    def subscribe_eventbridge(self) -> None:
        raise NotImplementedError("AWS EventBridge subscription is not wired in v1.7.x")

    def subscribe_eventgrid(self) -> None:
        raise NotImplementedError("Azure Event Grid subscription is not wired in v1.7.x")

    def subscribe_pubsub(self) -> None:
        raise NotImplementedError("GCP Pub/Sub subscription is not wired in v1.7.x")
