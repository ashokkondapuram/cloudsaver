from datetime import datetime, timezone

from app.collectors.azure_storage_policy import parse_management_policy
from app.multicloud_rules import evaluate_inventory as evaluate_multicloud
from app.agent_workflow_routing import route_for_rule
from app.governance_evidence import evaluate as evaluate_governance

NOW = datetime(2026, 10, 23, 18, tzinfo=timezone.utc)
STORAGE_ID = (
    '/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg/providers/'
    'Microsoft.Storage/storageAccounts/acct1'
)


def storage(**evidence):
    return dict(
        cloud_provider='azure',
        resource_id=STORAGE_ID,
        resource_type='microsoft.storage/storageaccounts',
        subscription_id='00000000-0000-4000-8000-000000000001',
        scope_id='00000000-0000-4000-8000-000000000001',
        observed_at=NOW.isoformat(),
        evidence=evidence,
    )


def test_absent_management_policy_triggers_lifecycle_review():
    parsed = parse_management_policy(None, absent=True)
    assert parsed['lifecycle_policy_verified'] is True
    assert parsed['multipart_abort_rule_present'] is False
    row = storage(**parsed)
    outcomes = evaluate_multicloud([row], now=NOW)
    match = next(item for item in outcomes if item['rule_id'] == 'AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD')
    assert match['outcome'] == 'condition_detected'


def test_enabled_lifecycle_without_multipart_abort_is_detected():
    body = {
        'properties': {
            'policy': {
                'rules': [
                    {
                        'enabled': True,
                        'definition': {
                            'actions': {
                                'baseBlob': {
                                    'tierToCool': {'daysAfterModificationGreaterThan': 30},
                                },
                            },
                        },
                    },
                ],
            },
        },
    }
    parsed = parse_management_policy(body)
    assert parsed['lifecycle_policy_verified'] is True
    assert parsed['multipart_abort_rule_present'] is False
    row = storage(**parsed)
    match = next(
        item for item in evaluate_multicloud([row], now=NOW)
        if item['rule_id'] == 'AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD'
    )
    assert match['outcome'] == 'condition_detected'


def test_multipart_abort_within_seven_days_is_not_detected():
    body = {
        'properties': {
            'policy': {
                'rules': [
                    {
                        'enabled': True,
                        'definition': {
                            'actions': {
                                'baseBlob': {
                                    'delete': {
                                        'abortIncompleteMultipartUpload': {
                                            'daysAfterCreationGreaterThan': 3,
                                        },
                                    },
                                },
                            },
                        },
                    },
                ],
            },
        },
    }
    parsed = parse_management_policy(body)
    assert parsed['multipart_abort_rule_present'] is True
    row = storage(**parsed)
    match = next(
        item for item in evaluate_multicloud([row], now=NOW)
        if item['rule_id'] == 'AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD'
    )
    assert match['outcome'] == 'condition_not_detected'


def test_abort_days_beyond_seven_triggers_review():
    row = storage(abort_incomplete_multipart_days=14, lifecycle_policy_verified=True)
    match = next(
        item for item in evaluate_multicloud([row], now=NOW)
        if item['rule_id'] == 'AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD'
    )
    assert match['outcome'] == 'condition_detected'


def test_governance_reads_allow_blob_public_access_from_typed_configuration():
    resource = storage(
        allow_blob_public_access=None,
        typed_configuration={'allowBlobPublicAccess': False},
    )
    scan = dict(scan_id='s1', timestamp=NOW.isoformat(), status='completed', data_origin='live')
    context = dict(
        application='payments',
        environment='production',
        classification='customer_data',
        technical_owner='00000000-0000-4000-8000-000000000099',
        business_owner='00000000-0000-4000-8000-000000000088',
        rationale='Confirmed production customer-data scope for this assessment.',
    )
    policy = dict(version=1, mandatory_obligation=False)
    result = evaluate_governance(resource, scan, context, policy, NOW)
    assert result['result'] == 'pass'
    assert result['configuration']['allow_blob_public_access'] is False


def test_storage_workflow_routes_to_engineering_review():
    route = route_for_rule('AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD')
    assert route.primary == 'engineering_review_plan'
    assert route.engineering_action == 'azure.storage.lifecycle.review'
