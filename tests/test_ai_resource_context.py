"""AI outbound context excludes resource_id but includes scan rule and cost fields."""
import json

from app.ai_scan_context import augment_ai_context_from_scan
from app.resource_assessment import merge
from tests.support import azure_disk_finding

SUB = '22222222-2222-4222-8222-222222222222'


def test_build_resource_ai_context_omits_resource_id():
    disk = azure_disk_finding(SUB)
    assessment, context = merge('k' * 64, [disk], observed_at='2026-10-22T00:00:00+00:00')
    assert 'resource_id' not in context
    assert context['resource_reference'] == assessment['resource_key']
    assert context['resource_name'] == disk['resource_name']
    assert disk['resource_id'] not in json.dumps(context)


def test_augment_adds_rule_evaluations_without_resource_id():
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
                reason='Need retention history.',
            )
        ],
    )
    enriched = augment_ai_context_from_scan(scan, assessment, [disk], base)
    assert enriched['rule_evaluations']
    assert 'resource_id' not in json.dumps(enriched)
    assert enriched['rule_evaluations'][0]['rule_id'] == 'AZURE_DISK_UNATTACHED_RETENTION'
