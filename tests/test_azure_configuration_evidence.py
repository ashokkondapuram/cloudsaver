from app.collectors.azure_configuration_evidence import enrich_configuration_evidence, enrich_inventory_configuration


def test_hydrate_typed_configuration_from_arg_flat_fields():
    resource = dict(
        resource_type='microsoft.compute/disks',
        resource_id='/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
        evidence=dict(source='Azure Resource Graph', disk_state='Unattached', size_gb=64, encrypted=True),
    )
    enrich_configuration_evidence(resource)
    typed = resource['evidence']['typed_configuration']
    assert typed['diskState'] == 'Unattached'
    assert typed['diskSizeGB'] == 64
    assert resource['evidence']['encrypted'] is True


def test_disk_configuration_from_arm_typed_configuration():
    resource = dict(
        resource_type='microsoft.compute/disks',
        resource_id='/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
        evidence=dict(
            typed_configuration=dict(
                diskState='Unattached',
                diskSizeGB=128,
                diskIOPSReadWrite=500,
                diskMBpsReadWrite=100,
                encryption=dict(type='EncryptionAtRestWithPlatformKey'),
            ),
        ),
    )
    enrich_configuration_evidence(resource)
    evidence = resource['evidence']
    assert evidence['disk_state'] == 'Unattached'
    assert evidence['size_gb'] == 128
    assert evidence['encrypted'] is True
    assert evidence['target_disk']['iops'] == 500
    assert evidence['analysis_readiness']['configuration'] == 'complete'
    assert 'AZURE_DISK_PROVISIONED_PERFORMANCE' in resource['unsupported_rule_ids']


def test_public_ip_association_from_configuration():
    resource = dict(
        resource_type='microsoft.network/publicipaddresses',
        resource_id='/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg/providers/Microsoft.Network/publicIPAddresses/pip1',
        evidence=dict(typed_configuration=dict(ipConfiguration=dict(id='nic/config'), natGateway=None)),
    )
    enrich_configuration_evidence(resource)
    assert resource['evidence']['association_verified'] is True
    assert 'AZURE_PUBLIC_IP_UNASSOCIATED' not in resource['unsupported_rule_ids']


def test_inventory_pass_applies_readiness():
    rows = enrich_inventory_configuration([dict(
        resource_type='microsoft.web/serverfarms',
        resource_id='/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg/providers/Microsoft.Web/serverFarms/plan1',
        evidence=dict(source='Azure Resource Graph', hosted_app_count=0, sku_tier='Standard'),
    )])
    readiness = rows[0]['evidence']['analysis_readiness']
    assert readiness['configuration'] in ('complete', 'partial')
    assert 'AZURE_ASP_UNDERUTILIZED_SKU' in readiness['telemetry_pending_rule_ids']


def test_storage_account_lifecycle_readiness_from_policy_evidence():
    resource = dict(
        resource_type='microsoft.storage/storageaccounts',
        resource_id='/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/acct1',
        evidence=dict(
            typed_configuration=dict(
                allowBlobPublicAccess=False,
                minimumTlsVersion='TLS1_2',
                encryption=dict(keySource='Microsoft.Storage'),
            ),
            lifecycle_policy_verified=True,
            multipart_abort_rule_present=False,
            allow_blob_public_access=False,
        ),
    )
    enrich_configuration_evidence(resource)
    readiness = resource['evidence']['analysis_readiness']
    assert readiness['configuration'] == 'complete'
    assert 'AZURE_STORAGE_LIFECYCLE_AND_ORPHANED_VHD' not in resource.get('unsupported_rule_ids', [])
