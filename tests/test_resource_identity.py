"""Centralized resource identity (canonical ids and resource_key)."""
from app.domain.resource.identity import canonical_resource_id, resource_key
from app.resource_assessment import resource_key as assessment_resource_key
from app.rule_detail import normalize_resource_id


def test_azure_canonical_id_lowercases():
    arm = '/subscriptions/AbCd/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm1'
    assert canonical_resource_id('azure', arm) == arm.lower()
    assert normalize_resource_id('azure', arm) == arm.lower()


def test_aws_arn_case_preserved():
    arn = 'arn:aws:ec2:us-east-1:123456789012:instance/i-0AbCdEf'
    assert canonical_resource_id('aws', arn) == arn
    assert normalize_resource_id('aws', arn) == arn


def test_resource_key_matches_after_normalize():
    provider = 'azure'
    mixed = '/subscriptions/X/resourceGroups/Y/providers/Microsoft.Storage/storageAccounts/SaName'
    canonical = canonical_resource_id(provider, mixed)
    assert resource_key(provider, mixed) == resource_key(provider, canonical)
    finding = {'cloud_provider': provider, 'resource_id': mixed}
    assert assessment_resource_key(finding) == resource_key(provider, canonical)

    aws_provider = 'aws'
    aws_arn = 'arn:aws:s3:::MyBucket'
    aws_canonical = canonical_resource_id(aws_provider, aws_arn)
    assert resource_key(aws_provider, aws_arn) == resource_key(aws_provider, aws_canonical)
