"""AI outbound context is minimized and excludes sensitive fields."""
import json

from app.ai_resource_context import build_resource_ai_context
from app.ai_scan_context import augment_ai_context_from_scan
from app.resource_assessment import merge
from tests.support import azure_disk_finding

SUB = '22222222-2222-4222-8222-222222222222'
SENSITIVE_KEYS = (
    'resource_id',
    'resource_name',
    'resource_group',
    'scope_id',
    'subscription_id',
    'billed_cost_usd',
    'effective_cost_usd',
    'configuration_detail',
    'costs',
    'details',
)


def test_build_resource_ai_context_omits_identifiers_and_billing():
    disk = azure_disk_finding(SUB)
    assessment, context = merge('k' * 64, [disk], observed_at='2026-10-22T00:00:00+00:00')
    blob = json.dumps(context)
    assert context['resource_reference'] == assessment['resource_key']
    assert disk['resource_id'] not in blob
    assert disk['resource_name'] not in blob
    for key in SENSITIVE_KEYS:
        assert f'"{key}"' not in blob


def test_findings_carry_allowlisted_facts_only():
    disk = azure_disk_finding(SUB)
    disk['evidence'] = dict(disk.get('evidence') or {}, encrypted=False, owner_email='secret@example.com')
    _, context = merge('k' * 64, [disk], observed_at='2026-10-22T00:00:00+00:00')
    finding = context['findings'][0]
    assert 'details' not in finding and 'evidence' not in finding
    assert 'owner_email' not in json.dumps(finding)
    assert finding['facts'].get('encrypted') is False


def test_augment_adds_rule_evaluations_without_reason_or_resource_id():
    disk = azure_disk_finding(SUB)
    assessment, base = merge('k' * 64, [disk], observed_at='2026-10-22T00:00:00+00:00')
    scan = dict(
        scan_id='s1',
        timestamp='2026-10-22T00:00:00+00:00',
        findings=[disk],
        inventory=[dict(
            cloud_provider='azure',
            resource_id=disk['resource_id'],
            resource_name=disk['resource_name'],
            resource_type=disk['resource_type'],
            resource_group=disk['resource_group'],
            subscription_id=SUB,
            scope_id=SUB,
            evidence={},
        )],
        rule_evaluations=[
            dict(
                cloud_provider='azure',
                resource_id=disk['resource_id'],
                rule_id='AZURE_DISK_UNATTACHED_RETENTION',
                rule_version='1.0',
                outcome='insufficient_evidence',
                reason='Need retention history for /subscriptions/private/disks/x.',
            )
        ],
    )
    enriched = augment_ai_context_from_scan(scan, assessment, [disk], base)
    row = enriched['rule_evaluations'][0]
    assert row['rule_id'] == 'AZURE_DISK_UNATTACHED_RETENTION'
    assert 'reason' not in row
    assert 'resource_id' not in json.dumps(enriched)
    assert '/subscriptions/' not in json.dumps(enriched)
