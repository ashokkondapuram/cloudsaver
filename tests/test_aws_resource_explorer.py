"""AWS Resource Explorer 2 inventory collector (Stubber, no live AWS)."""
from datetime import datetime, timezone

import boto3
from botocore.stub import Stubber

from app.collectors.aws_resource_explorer import (
    enabled,
    inventory_rows,
    merge_by_arn,
)

ACCOUNT = '123456789012'
REGION = 'us-east-1'
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def test_enabled_respects_env(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_AWS_RESOURCE_EXPLORER', raising=False)
    assert enabled() is False
    monkeypatch.setenv('CLOUDSAVER_AWS_RESOURCE_EXPLORER', 'true')
    assert enabled() is True


def test_merge_by_arn_prefers_primary_rows():
    primary = [dict(resource_id='arn:aws:ec2:us-east-1:123456789012:instance/i-1', evidence={'source': 'AWS live reader APIs'})]
    supplemental = [
        dict(resource_id='arn:aws:ec2:us-east-1:123456789012:instance/i-1', evidence={'source': 'AWS Resource Explorer 2'}),
        dict(resource_id='arn:aws:ec2:us-east-1:123456789012:instance/i-2', evidence={'source': 'AWS Resource Explorer 2'}),
    ]
    merged = merge_by_arn(primary, supplemental)
    assert len(merged) == 2
    assert merged[0]['evidence']['source'] == 'AWS live reader APIs'
    assert merged[1]['resource_id'].endswith('/i-2')


def test_inventory_rows_paginates_search(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AWS_RESOURCE_EXPLORER', 'true')
    session = boto3.Session(
        aws_access_key_id='offline-test',
        aws_secret_access_key='offline-test',
        region_name=REGION,
    )
    explorer = session.client('resource-explorer-2')
    stub = Stubber(explorer)
    stub.add_response(
        'search',
        {
            'Resources': [
                {
                    'Arn': f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-page1',
                    'ResourceType': 'ec2:instance',
                    'Service': 'ec2',
                    'Region': REGION,
                }
            ],
            'NextToken': 'page-2',
        },
        {'QueryString': f'region:{REGION}', 'MaxResults': 1000},
    )
    stub.add_response(
        'search',
        {
            'Resources': [
                {
                    'Arn': f'arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/app/prod',
                    'ResourceType': 'logs:log-group',
                    'Service': 'logs',
                    'Region': REGION,
                }
            ],
        },
        {'QueryString': f'region:{REGION}', 'MaxResults': 1000, 'NextToken': 'page-2'},
    )

    class Client:
        def __call__(self, service):
            assert service == 'resource-explorer-2'
            return explorer

    with stub:
        rows = inventory_rows(Client(), ACCOUNT, REGION, now=NOW)
    stub.assert_no_pending_responses()

    assert len(rows) == 2
    by_arn = {row['resource_id']: row for row in rows}
    ec2 = by_arn[f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-page1']
    assert ec2['resource_type'] == 'aws:ec2:instance'
    assert ec2['resource_name'] == 'i-page1'
    assert ec2['evidence']['source'] == 'AWS Resource Explorer 2'
    logs = by_arn[f'arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/app/prod']
    assert logs['resource_type'] == 'aws:logs:log-group'


def test_inventory_rows_skips_foreign_account(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AWS_RESOURCE_EXPLORER', 'true')
    session = boto3.Session(
        aws_access_key_id='offline-test',
        aws_secret_access_key='offline-test',
        region_name=REGION,
    )
    explorer = session.client('resource-explorer-2')
    stub = Stubber(explorer)
    stub.add_response(
        'search',
        {
            'Resources': [
                {
                    'Arn': 'arn:aws:ec2:us-west-2:999999999999:instance/i-foreign',
                    'ResourceType': 'ec2:instance',
                    'Service': 'ec2',
                    'Region': 'us-west-2',
                }
            ],
        },
        {'QueryString': f'region:{REGION}', 'MaxResults': 1000},
    )

    class Client:
        def __call__(self, service):
            return explorer

    with stub:
        assert inventory_rows(Client(), ACCOUNT, REGION, now=NOW) == []
    stub.assert_no_pending_responses()
