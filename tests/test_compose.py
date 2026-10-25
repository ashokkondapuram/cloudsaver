"""compose.yaml runs CloudSaver only; the platform (identity, portal, billing) is a separate compose project."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / 'compose.yaml').read_text()
CALLERS = {'api-gateway':'GATEWAY','scanner-service':'SCANNER','agent-gateway':'AGENT'}


def sections():
    """Top-level keys to their indented bodies (the test image has no YAML parser)."""
    result, name = {}, None
    for line in TEXT.splitlines():
        if line and not line[0].isspace() and not line.startswith('#'):
            name = line.split(':', 1)[0]
            result[name] = []
        elif name:
            result[name].append(line)
    return result


def services():
    result, name = {}, None
    for line in sections()['services']:
        match = re.match(r'^  ([a-z0-9-]+):\s*$', line)
        if match:
            name = match.group(1)
            result[name] = []
        elif name:
            result[name].append(line)
    return {k: '\n'.join(v) for k, v in result.items()}


def test_only_cloudsaver_services_run_here():
    names = set(services())
    assert names == {'migrate', 'api-gateway', 'scanner-service', 'web-dashboard', 'scan-worker', 'delivery-dispatcher', 'scan-scheduler',
                     'postgres', 'redis', 'agent-gateway', 'agent-worker', 'data-retention-worker', 'billing-sync-worker', 'governance-monitor'}
    # Provider bill ingestion belongs to CloudSaver; platform subscription billing remains separate.
    assert not any(word in name for name in names for word in ('identity', 'portal', 'token'))


def test_no_platform_database_redis_or_billing_settings():
    for text in ('identity-db', 'token-db', 'IDENTITY_DATABASE_URL', 'IDENTITY_DB_', 'TOKEN_DB_',
                 'CLOUDSAVER_IDENTITY_REDIS_URL', 'CLOUDSAVER_KEY_PEPPER', 'CLOUDSAVER_IDENTITY_CALLERS',
                 'CLOUDSAVER_OPERATOR_KEY_SHA256', 'CLOUDSAVER_PORTAL_AUTH', 'BILLING_RETURN'):
        assert text not in TEXT, text
    assert 'stripe' not in TEXT.lower()


def test_identity_callers_join_the_external_platform_link_with_their_own_token():
    found = services()
    for name, caller in CALLERS.items():
        body = found[name]
        assert re.search(r'^    networks: \[default, platform-link\]$', body, re.M), name
        assert f'CLOUDSAVER_IDENTITY_TOKEN: ${{CLOUDSAVER_IDENTITY_TOKEN_{caller}:-}}' in body, name
    for name in set(found) - set(CALLERS):
        assert 'platform-link' not in found[name], name
    networks = '\n'.join(sections()['networks'])
    assert re.search(r'platform-link:\n\s+external: true', networks)
    assert 'CLOUDSAVER_IDENTITY_URL: ${CLOUDSAVER_IDENTITY_URL:-http://identity-service:8005}' in TEXT


def test_published_ports_bind_to_loopback_only():
    ports = []
    lines = TEXT.splitlines()
    for index, line in enumerate(lines):
        inline = re.match(r'^\s+ports:\s*\[(.*)\]\s*$', line)
        if inline:
            ports += [p.strip().strip('\'"') for p in inline.group(1).split(',') if p.strip()]
        elif re.match(r'^\s+ports:\s*$', line):
            for item in lines[index + 1:]:
                entry = re.match(r'^\s+-\s*(.+)$', item)
                if not entry:
                    break
                ports.append(entry.group(1).strip('\'"'))
    assert ports, 'expected published ports'
    assert all(p.startswith('127.0.0.1:') for p in ports), ports
    assert 'network_mode' not in TEXT


def test_governance_verifier_secrets_never_reach_agents_or_public_ports():
    found=services()
    assert 'workers.governance_monitor' in found['governance-monitor']
    assert 'ports:' not in found['governance-monitor']
    for name,body in found.items():
        if name not in ('scanner-service','governance-monitor'):assert 'CLOUDSAVER_GOVERNANCE_KEY_PRIMARY' not in body
    assert all('CLOUDSAVER_GOVERNANCE_KEY_PRIMARY' in found[name] for name in ('scanner-service','governance-monitor'))


def test_host_azure_cache_is_shared_only_by_read_side_services():
    found = services()
    readers = {'scanner-service', 'scan-worker', 'billing-sync-worker'}
    assert '${CLOUDSAVER_AZURE_CONFIG_DIR:-azure-developer-cache}:/home/appuser/.azure' in found['scanner-service']
    for name, body in found.items():
        if name in readers:
            assert 'AZURE_CONFIG_DIR: /home/appuser/.azure' in body
            assert 'user: ${CLOUDSAVER_AZURE_CACHE_USER:-10001:10001}' in body
            assert 'volumes: *azure_cache' in body or 'volumes: &azure_cache' in body
        else:
            assert 'azure_cache' not in body
            assert 'AZURE_CONFIG_DIR' not in body
