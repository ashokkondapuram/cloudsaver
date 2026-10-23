"""AWS inventory through a keyless reader role, with scope checks and no demo fallback."""
from app.cloud_scope import validate_finding_scope
from app.scanner import ScanError


def scan_account(source, *, session=None):
    account, region = source['account_id'], source['region']
    clients = []
    if session is None:
        from app.cloud_identity import CredentialError, aws_session
        try:
            session = aws_session(source)
        except CredentialError:
            raise ScanError('The AWS reader role is unavailable') from None
    try:
        from botocore.config import Config
        config = Config(connect_timeout=10, read_timeout=45, retries={'max_attempts': 3, 'mode': 'standard'})
        def client(service):
            value = session.client(service, region_name=region, config=config)
            clients.append(value)
            return value
        if client('sts').get_caller_identity().get('Account') != account:
            raise ScanError('AWS caller does not match the configured account')
        ec2, rds = client('ec2'), client('rds')
        findings, seen, total = [], set(), 0

        def add(rule, kind, name, row, details):
            rid = (f'arn:aws:rds:{region}:{account}:db:{name}' if kind == 'db'
                   else f'arn:aws:ec2:{region}:{account}:{kind}/{name}')
            if kind == 'db' and row.get('DBInstanceArn') != rid:
                raise ScanError('RDS returned an inconsistent account identity')
            evidence = {'source': 'AWS read-only APIs', 'region': region,
                        'tags': {tag['Key']: tag['Value'] for tag in (row.get('Tags') or row.get('TagList') or [])
                                 if isinstance(tag, dict) and isinstance(tag.get('Key'), str) and isinstance(tag.get('Value'), str)}}
            for source_key, key in [('Encrypted', 'encrypted'), ('StorageEncrypted', 'encrypted'),
                                    ('MultiAZ', 'multi_az'), ('PubliclyAccessible', 'publicly_accessible'),
                                    ('DeletionProtection', 'deletion_protection')]:
                if type(row.get(source_key)) is bool:
                    evidence[key] = row[source_key]
            for source_key, key in [('BackupRetentionPeriod', 'backup_retention_days'), ('Size', 'size_gb'), ('Iops', 'provisioned_iops')]:
                if type(row.get(source_key)) is int and row[source_key] >= 0:
                    evidence[key] = row[source_key]
            result = dict(rule_id=rule, severity='MEDIUM' if kind == 'elastic-ip' else 'HIGH',
                cloud_provider='aws', scope_id=account, subscription_id=account, region=region,
                resource_id=rid, resource_name=name, resource_group=region,
                resource_type='aws:rds:db' if kind == 'db' else 'aws:ec2:' + kind,
                estimated_monthly_waste_usd=None, details=details,
                evidence=evidence)
            validate_finding_scope(result, {'aws_accounts': [source]})
            if rid not in seen:
                findings.append(result)
                seen.add(rid)

        def rows(api, operation, field, **kwargs):
            nonlocal total
            token, seen_tokens = None, set()
            for _ in range(1000):
                response = getattr(api, operation)(**dict(kwargs, **({'NextToken' if operation == 'describe_volumes' else 'Marker': token} if token else {})))
                batch = response.get(field)
                if not isinstance(batch, list):
                    raise ScanError('AWS returned malformed inventory')
                total += len(batch)
                if total > 100000:
                    raise ScanError('AWS inventory resource limit exceeded')
                yield from batch
                token = response.get('NextToken' if operation == 'describe_volumes' else 'Marker')
                if not token:
                    return
                if not isinstance(token, str) or token in seen_tokens:
                    raise ScanError('AWS repeated an invalid continuation token')
                seen_tokens.add(token)
            raise ScanError('AWS exceeded its inventory page limit')

        for row in rows(ec2, 'describe_volumes', 'Volumes', Filters=[{'Name': 'status', 'Values': ['available']}], MaxResults=500):
            if row.get('State') == 'available' and row.get('Attachments') == []:
                add('AWS_UNATTACHED_EBS', 'volume', row['VolumeId'], row,
                    'Available EBS volume has no attachments. Validate retention, snapshots and recovery. Pricing and realizable savings are unknown.')
        addresses = ec2.describe_addresses().get('Addresses')
        if not isinstance(addresses, list) or len(addresses) > 100000:
            raise ScanError('AWS returned invalid address inventory')
        for row in addresses:
            if row.get('AllocationId') and not row.get('AssociationId') and not row.get('NetworkInterfaceId') and not row.get('InstanceId'):
                add('AWS_UNASSOCIATED_EIP', 'elastic-ip', row['AllocationId'], row,
                    'Allocated VPC Elastic IP has no association. Releasing it may lose a reserved address; validate dependencies.')
        for row in rows(rds, 'describe_db_instances', 'DBInstances', MaxRecords=100):
            if row.get('DBInstanceStatus') == 'stopped':
                add('AWS_IDLE_RDS', 'db', row['DBInstanceIdentifier'], row,
                    'RDS instance is stopped. Storage and backup charges may remain; state does not prove idle duration or deletability.')
        return findings
    except ScanError:
        raise
    except Exception:
        raise ScanError('AWS scan failed; no demo fallback or partial inventory was saved') from None
    finally:
        for value in clients:
            value.close()
