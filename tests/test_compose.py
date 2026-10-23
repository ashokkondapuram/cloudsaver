"""compose.yaml runs CloudSaver only; the platform (identity, portal, billing) is a separate compose project."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / 'compose.yaml').read_text()
CALLERS = {'api-gateway': 'GATEWAY', 'tenant-service': 'TENANT', 'scanner-service': 'SCANNER',
           'analytics-service': 'ANALYTICS', 'notification-service': 'NOTIFICATION'}


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
    assert names == {'migrate', 'api-gateway', 'tenant-service', 'scanner-service', 'analytics-service',
                     'notification-service', 'web-dashboard', 'scan-worker', 'delivery-dispatcher', 'scan-scheduler',
                     'postgres', 'redis'}
    assert not any(word in name for name in names for word in ('identity', 'portal', 'token', 'billing'))


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
