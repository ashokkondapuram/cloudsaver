from uuid import uuid4
import pytest

from app.remediation_terraform import generate_terraform_hcl

TENANT = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
DISK = f'/subscriptions/{SUB}/resourceGroups/prod/providers/Microsoft.Compute/disks/disk-one'


def scan(mode='azure', **finding):
    return dict(mode=mode, status='completed', findings=[dict(resource_id=DISK, subscription_id=SUB, rule_id='ORPHANED_DISK', **finding)])


def test_import_only_without_guessed_settings_or_destruction():
    hcl = generate_terraform_hcl(scan(), [DISK], TENANT, [SUB])
    assert 'import {' in hcl and DISK in hcl and f'tenant_id = "{TENANT}"' in hcl
    assert f'subscription_id = "{SUB}"' in hcl
    assert 'plan -generate-config-out=' in hcl
    for unsafe in ('resource "', 'eastus', 'disk_size_gb', 'plan -destroy', 'terraform apply', 'snapshot_'):
        assert unsafe not in hcl


@pytest.mark.parametrize('mode', ['multi-cloud', 'unknown', None])
def test_non_live_scan_rejected(mode):
    with pytest.raises(ValueError):
        generate_terraform_hcl(scan(mode), [DISK], TENANT, [SUB])


def test_rejects_cross_subscription_duplicates_unsupported_and_inconsistent_rules():
    with pytest.raises(ValueError):
        generate_terraform_hcl(scan(), [DISK], TENANT, [str(uuid4())])
    with pytest.raises(ValueError):
        generate_terraform_hcl(scan(), [DISK, DISK.upper()], TENANT, [SUB])
    bad = scan()
    bad['findings'][0]['rule_id'] = 'UNASSOCIATED_PUBLIC_IP'
    with pytest.raises(ValueError):
        generate_terraform_hcl(bad, [DISK], TENANT, [SUB])


def test_identical_names_in_different_groups_have_unique_labels():
    other = DISK.replace('/prod/', '/other/')
    record = scan()
    record['findings'].append(dict(record['findings'][0], resource_id=other))
    hcl = generate_terraform_hcl(record, [DISK, other], TENANT, [SUB])
    assert hcl.count('import {') == 2
    labels = [line for line in hcl.splitlines() if 'to = azurerm_managed_disk.' in line]
    assert len(set(labels)) == 2
