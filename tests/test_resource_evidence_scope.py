from app.resource_evidence_scope import check_allowed, evidence_profile


def _finding(rtype, **evidence):
    return dict(
        cloud_provider='azure',
        resource_type=rtype,
        resource_id=f'/subscriptions/x/resourceGroups/rg/providers/{rtype}/n1',
        rule_id='INVENTORY_OBSERVATION',
        evidence=evidence,
    )


def test_app_service_plan_skips_vm_disk_performance_checks():
    profile = evidence_profile(_finding('Microsoft.Web/serverFarms', hosted_app_count=0, sku_name='P1v3'))
    assert profile.family == 'app-service'
    assert not check_allowed('BURST_CREDITS', profile)
    assert not check_allowed('DISK_QUEUE', profile)
    assert not check_allowed('PATCH_CURRENCY', profile)
    assert check_allowed('APPLICATION_DENSITY', profile)
    assert check_allowed('CFS_THROTTLING', profile)


def test_managed_disk_skips_app_and_vm_only_checks():
    profile = evidence_profile(_finding('Microsoft.Compute/disks', disk_state='Unattached'))
    assert profile.family == 'managed-disks'
    assert check_allowed('DISK_QUEUE', profile)
    assert check_allowed('UNATTACHED_DURATION', profile)
    assert not check_allowed('APPLICATION_DENSITY', profile)
    assert not check_allowed('PATCH_CURRENCY', profile)
    assert not check_allowed('HTTP_THROTTLING', profile)


def test_virtual_machine_utilization_metrics():
    profile = evidence_profile(_finding('Microsoft.Compute/virtualMachines', power_state='PowerState/running'))
    assert 'cpu_percent' in profile.utilization_metrics
    assert check_allowed('BURST_CREDITS', profile)
    assert not check_allowed('APPLICATION_DENSITY', profile)


def test_public_ip_profile_is_minimal():
    profile = evidence_profile(_finding('Microsoft.Network/publicIPAddresses', association_verified=False))
    assert profile.family == 'ip-nat'
    assert not check_allowed('BURST_CREDITS', profile)
    assert not check_allowed('PATCH_CURRENCY', profile)
    assert not check_allowed('APPLICATION_DENSITY', profile)


def test_orphan_nic_uses_network_orphan_family():
    profile = evidence_profile(_finding('Microsoft.Network/networkInterfaces'))
    assert profile.family == 'network-orphan'
    assert check_allowed('FLOW_LOGS', profile)


def test_web_site_uses_app_service_metrics():
    profile = evidence_profile(_finding('Microsoft.Web/sites'))
    assert profile.family == 'app-service'
    assert 'requests' in profile.utilization_metrics or 'cpu_percent' in profile.utilization_metrics
