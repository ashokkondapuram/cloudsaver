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


def test_subscribe_hooks_not_implemented():
    consumer = EventStreamConsumer()
    with pytest.raises(NotImplementedError):
        consumer.subscribe_eventbridge()
