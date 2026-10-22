import subprocess

import pytest

from app.remediation import generate_script

TENANT = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
DISK = f'/subscriptions/{SUB}/resourceGroups/test-rg/providers/Microsoft.Compute/disks/test-disk'
IP = f'/subscriptions/{SUB}/resourceGroups/test-rg/providers/Microsoft.Network/publicIPAddresses/test-ip'


def scan(rid=DISK, rule='ORPHANED_DISK'):
    return dict(mode='azure', status='completed', findings=[dict(resource_id=rid, rule_id=rule, subscription_id=SUB)])


def test_disk_script_requires_exact_confirmation_and_live_state_recheck(tmp_path):
    script = generate_script(scan(), [DISK], TENANT, [SUB])
    assert '[ -t 0 ]' in script
    assert script.index('read -r confirmation') < script.index('disk_state=$(az disk show') < script.index('az disk delete')
    assert '--subscription "$subscription_id"' in script
    assert '[ "$disk_state" = "Unattached" ]' in script
    path = tmp_path / 'remediate.sh'
    path.write_text(script)
    assert subprocess.run(['bash', '-n', str(path)], capture_output=True).returncode == 0


def test_public_ip_checks_both_associations():
    script = generate_script(scan(IP, 'UNASSOCIATED_PUBLIC_IP'), [IP], TENANT, [SUB])
    assert 'ipConfiguration.id == `null` && natGateway.id == `null`' in script
    assert '[ "$unassociated" = "true" ]' in script
    assert script.index('unassociated=$(az network public-ip show') < script.index('az network public-ip delete')
    assert '--yes' not in script


@pytest.mark.parametrize('mode,status', [('multi-cloud', 'completed'), ('azure', 'running'), ('unknown', 'completed')])
def test_refuses_non_azure_and_incomplete_scan(mode, status):
    record = scan()
    record.update(mode=mode, status=status)
    with pytest.raises(ValueError):
        generate_script(record, [DISK], TENANT, [SUB])


def test_refuses_other_scan_unknown_rule_and_subscription():
    with pytest.raises(ValueError, match='belong'):
        generate_script(scan(), [IP], TENANT, [SUB])
    with pytest.raises(ValueError, match='Only unattached'):
        generate_script(scan(rule='STOPPED_VM'), [DISK], TENANT, [SUB])
    with pytest.raises(ValueError, match='not authorized'):
        generate_script(scan(), [DISK], TENANT, [TENANT])


@pytest.mark.parametrize('suffix', [';touch injected', '$(touch injected)', '\nexit 0', "' ; exit 0; '", '/nested'])
def test_rejects_shell_injection_resource_names(suffix):
    rid = DISK + suffix
    with pytest.raises(ValueError, match='identity'):
        generate_script(scan(rid), [rid], TENANT, [SUB])


def test_refuses_duplicate_and_oversized_selection():
    with pytest.raises(ValueError, match='unique'):
        generate_script(scan(), [DISK, DISK], TENANT, [SUB])
    with pytest.raises(ValueError, match='between'):
        generate_script(scan(), [DISK] * 51, TENANT, [SUB])


def test_script_cannot_execute_with_piped_approval(tmp_path):
    # Stub az only to satisfy command lookup. The TTY gate must abort before any cloud command.
    az = tmp_path / 'az'
    az.write_text('#!/bin/sh\necho CALLED >&2\nexit 1\n')
    az.chmod(0o700)
    script = generate_script(scan(), [DISK], TENANT, [SUB])
    import os
    result = subprocess.run(['bash'], input=script, capture_output=True, text=True,
                            env={**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH']})
    assert result.returncode != 0
    assert 'Interactive terminal' in result.stderr
    assert 'CALLED' not in result.stderr
