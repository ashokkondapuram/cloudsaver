"""Shared helpers for API and worker tests."""


def azure_disk_finding(subscription_id: str) -> dict:
    return dict(
        rule_id='ORPHANED_DISK',
        severity='HIGH',
        resource_name='archive-export-disk',
        resource_type='microsoft.compute/disks',
        resource_group='review',
        subscription_id=subscription_id,
        resource_id=f'/subscriptions/{subscription_id}/resourceGroups/review/providers/microsoft.compute/disks/archive-export-disk',
        estimated_monthly_waste_usd=None,
        details='Unattached managed disk for review',
        cloud_provider='azure',
    )


def stub_scanner(tenant):
    return [azure_disk_finding(tenant['subscription_ids'][0])]
