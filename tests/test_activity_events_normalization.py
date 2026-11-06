"""Unit tests for Stream D activity normalization."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from app.analysis_service.context import ActivityEvent
from app.analysis_service.loader import context_from_inventory_row
from app.collectors.activity_events import (
    append_activity_events,
    is_iac_authorized,
    normalize_activity_event,
)


def test_azure_activity_normalization():
    payload = {
        'eventDataId': 'azure-evt-1',
        'eventTimestamp': '2026-10-15T10:00:00Z',
        'operationName': {'value': 'Microsoft.Compute/virtualMachines/write'},
        'claims': {'upn': 'console-user@contoso.com'},
        'properties': {'requestbody': {'hardwareProfile': {'vmSize': 'Standard_D2s_v3'}}},
    }
    out = normalize_activity_event(provider='azure', payload=payload)
    assert out == {
        'event_id': 'azure-evt-1',
        'event_time': '2026-10-15T10:00:00Z',
        'event_name': 'Microsoft.Compute/virtualMachines/write',
        'actor_identity': 'console-user@contoso.com',
        'changed_fields': ['hardwareProfile'],
        'is_iac_authorized': False,
    }
    ActivityEvent.model_validate(out)


def test_aws_cloudtrail_normalization_and_iac_detection(monkeypatch):
    monkeypatch.setenv(
        'CLOUDSAVER_IAC_PRINCIPAL_PATTERNS',
        'terraform,github-actions,cloudformation',
    )
    payload = {
        'EventId': 'aws-evt-1',
        'EventName': 'ModifyInstanceAttribute',
        'EventTime': datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        'CloudTrailEvent': (
            '{"userIdentity":{"arn":"arn:aws:sts::123:assumed-role/github-actions/deploy"},'
            '"requestParameters":{"instanceType":"t3.large"}}'
        ),
    }
    out = normalize_activity_event(provider='aws', payload=payload)
    assert out['event_id'] == 'aws-evt-1'
    assert out['event_name'] == 'ModifyInstanceAttribute'
    assert out['is_iac_authorized'] is True
    assert 'instanceType' in out['changed_fields']
    assert is_iac_authorized('arn:aws:iam::123:user/terraform-ci') is True
    assert is_iac_authorized('alice@example.com') is False


def test_gcp_audit_normalization():
    payload = {
        'insertId': 'gcp-insert-1',
        'timestamp': '2026-09-01T08:30:00Z',
        'protoPayload': {
            'methodName': 'v1.compute.instances.setMetadata',
            'authenticationInfo': {'principalEmail': 'ops@example.com'},
            'request': {'fingerprint': 'abc', 'items': []},
        },
    }
    out = normalize_activity_event(provider='gcp', payload=payload)
    assert out['event_id'] == 'gcp-insert-1'
    assert out['event_name'] == 'v1.compute.instances.setMetadata'
    assert out['actor_identity'] == 'ops@example.com'
    assert set(out['changed_fields']) == {'fingerprint', 'items'}


def test_append_activity_events_caps_length():
    evidence: dict = {}
    batch = [
        dict(
            event_id=f'evt-{index}',
            event_time=f'2026-01-{index + 1:02d}T00:00:00Z',
            event_name='write',
            actor_identity='',
            changed_fields=[],
            is_iac_authorized=False,
        )
        for index in range(25)
    ]
    append_activity_events(evidence, batch, limit=20)
    assert len(evidence['activity_events']) == 20


def test_loader_prefers_activity_events_over_state_history():
    row = {
        'cloud_provider': 'aws',
        'resource_id': 'arn:aws:ec2:us-east-1:1:instance/i-1',
        'resource_type': 'aws:ec2:instance',
        'evidence': {
            'activity_events': [
                {
                    'event_id': 'normalized-1',
                    'event_time': '2026-10-01T00:00:00Z',
                    'event_name': 'StopInstances',
                    'actor_identity': 'terraform@ci',
                    'changed_fields': [],
                    'is_iac_authorized': True,
                }
            ],
            'state_history': [
                {
                    'state': 'Stopped',
                    'start': '2026-09-01T00:00:00Z',
                    'end': '2026-10-01T00:00:00Z',
                    'complete': True,
                    'actor': 'console',
                }
            ],
        },
    }
    ctx = context_from_inventory_row(row)
    assert len(ctx.activity) == 1
    assert ctx.activity[0].event_id == 'normalized-1'
    assert ctx.activity[0].is_iac_authorized is True


def test_default_iac_patterns_without_env(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_IAC_PRINCIPAL_PATTERNS', raising=False)
    assert is_iac_authorized('CloudFormation-StackSet') is True
