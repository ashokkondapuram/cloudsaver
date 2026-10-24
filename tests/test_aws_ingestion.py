"""Exercise the AWS SDK contracts with botocore Stubber, without cloud requests."""
from contextlib import ExitStack

import boto3
from botocore.stub import Stubber
import pytest

from app.scanner import ScanError
from app.scanner_aws import scan_account

SOURCE = dict(account_id='123456789012', region='us-east-1', role_arn='arn:aws:iam::123456789012:role/CloudSaverReader')


def setup_stack(account='123456789012'):
    stack = ExitStack()
    session = boto3.Session(aws_access_key_id='offline-test', aws_secret_access_key='offline-test', region_name='us-east-1')
    clients = {name: session.client(name) for name in ('sts','ec2','rds')}
    stubs = {name: stack.enter_context(Stubber(client)) for name, client in clients.items()}
    stubs['sts'].add_response('get_caller_identity', {'Account':account, 'Arn':f'arn:aws:iam::{account}:user/test', 'UserId':'test'})
    class Session:
        def client(self, name, **kwargs):
            return clients[name]
    return stack, stubs, Session()


def test_aws_complete_pagination_and_account_validation():
    stack, stubs, session = setup_stack()
    with stack:
        first = {'MaxResults':500}
        stubs['ec2'].add_response('describe_volumes', {'Volumes':[dict(VolumeId='vol-08a9c2b4d1ef50123',State='available',Attachments=[])], 'NextToken':'next'}, first)
        stubs['ec2'].add_response('describe_volumes', {'Volumes':[dict(VolumeId='vol-0b73e512c98a34211',State='in-use',Attachments=[])]}, dict(first,NextToken='next'))
        stubs['ec2'].add_response('describe_addresses', {'Addresses':[dict(AllocationId='eipalloc-01f2a3b4c5d6e7f80'),
            dict(AllocationId='eipalloc-09a8b7c6d5e4f3a21',NetworkInterfaceId='eni-12345678')]})
        stubs['rds'].add_response('describe_db_instances', {'DBInstances':[dict(DBInstanceIdentifier='staging-db',DBInstanceStatus='stopped',
            DBInstanceArn='arn:aws:rds:us-east-1:123456789012:db:staging-db')], 'Marker':'next'}, {'MaxRecords':100})
        stubs['rds'].add_response('describe_db_instances', {'DBInstances':[]}, {'MaxRecords':100,'Marker':'next'})
        result = scan_account(SOURCE, session=session)
        assert len(result) == 3
        assert len(result.inventory) == 5  # Attached volumes and associated IPs remain in inventory.
        assert {f['rule_id'] for f in result} == {'AWS_UNATTACHED_EBS','AWS_UNASSOCIATED_EIP','AWS_IDLE_RDS'}
        assert all(f['estimated_monthly_waste_usd'] is None for f in result)
        for stub in stubs.values():
            stub.assert_no_pending_responses()


def test_aws_foreign_caller_is_rejected_before_inventory():
    stack, _, session = setup_stack('999999999999')
    with stack, pytest.raises(ScanError, match='configured account'):
        scan_account(SOURCE, session=session)


@pytest.mark.parametrize('failure', ['late', 'foreign-rds'])
def test_aws_late_failure_never_returns_demo_or_partial(failure):
    stack, stubs, session = setup_stack()
    with stack:
        stubs['ec2'].add_response('describe_volumes', {'Volumes':[dict(VolumeId='vol-08a9c2b4d1ef50123',State='available',Attachments=[])]})
        stubs['ec2'].add_response('describe_addresses', {'Addresses':[]})
        if failure == 'late':
            stubs['rds'].add_client_error('describe_db_instances', service_error_code='AccessDenied', service_message='private failure')
        else:
            stubs['rds'].add_response('describe_db_instances', {'DBInstances':[dict(DBInstanceIdentifier='staging-db',DBInstanceStatus='stopped',
                DBInstanceArn='arn:aws:rds:us-east-1:999999999999:db:staging-db')]})
        with pytest.raises(ScanError) as result:
            scan_account(SOURCE, session=session)
        assert 'private' not in str(result.value)


def test_aws_retains_only_explicit_settings_and_protection_intent():
    stack, stubs, session = setup_stack()
    with stack:
        stubs['ec2'].add_response('describe_volumes', {'Volumes':[dict(VolumeId='vol-08a9c2b4d1ef50123',State='available',Attachments=[],
            Encrypted=False,Size=128,Iops=3000,Tags=[{'Key':'Role','Value':'DR-Standby'}])]})
        stubs['ec2'].add_response('describe_addresses', {'Addresses':[]})
        stubs['rds'].add_response('describe_db_instances', {'DBInstances':[dict(DBInstanceIdentifier='staging-db',DBInstanceStatus='stopped',
            DBInstanceArn='arn:aws:rds:us-east-1:123456789012:db:staging-db',MultiAZ=False,BackupRetentionPeriod=0,
            StorageEncrypted=True,PubliclyAccessible=False,DeletionProtection=True)]})
        volume, database = scan_account(SOURCE, session=session)
        assert volume['evidence']['encrypted'] is False and volume['evidence']['size_gb'] == 128
        assert volume['evidence']['tags'] == {'Role':'DR-Standby'}
        assert database['evidence']['backup_retention_days'] == 0 and database['evidence']['multi_az'] is False
        assert database['evidence']['publicly_accessible'] is False and database['evidence']['deletion_protection'] is True
        assert 'recent_snapshot_verified' not in volume['evidence']
