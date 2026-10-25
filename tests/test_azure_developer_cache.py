"""Exercise the real SDK subprocess boundary with a synthetic CLI/cache, never Azure."""
import json
import os
import sys

import pytest
from azure.identity import CredentialUnavailableError

from app.cloud_identity import azure_credential


TENANT = '11111111-1111-4111-8111-111111111111'


@pytest.fixture
def local_cli(tmp_path, monkeypatch):
    cache = tmp_path / 'host cache with spaces'
    cache.mkdir()
    binary = tmp_path / 'bin'
    binary.mkdir()
    cli = binary / 'az'
    cli.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, sys
cache = pathlib.Path(os.environ['AZURE_CONFIG_DIR'])
(cache / 'invocation.json').write_text(json.dumps(sys.argv[1:]))
login = cache / 'test-login.json'
if not login.exists():
    print("Please run 'az login' to set up an account", file=sys.stderr)
    sys.exit(1)
print(login.read_text())
''')
    cli.chmod(0o700)
    monkeypatch.setenv('PATH', str(binary) + os.pathsep + os.environ.get('PATH', ''))
    monkeypatch.setenv('AZURE_CONFIG_DIR', str(cache))
    monkeypatch.setenv('CLOUDSAVER_CLOUD_IDENTITY', 'developer')
    return cache


def test_developer_credential_reads_selected_cache_and_preserves_tenant(local_cli):
    (local_cli / 'test-login.json').write_text(json.dumps({
        'accessToken': 'synthetic-cache-token', 'expires_on': 4102444800,
        'expiresOn': '2100-01-01 00:00:00.000000',
    }))
    credential = azure_credential({'tenant_id': TENANT}, settings={})
    try:
        assert credential.get_token('https://management.azure.com/.default').token == 'synthetic-cache-token'
        args = json.loads((local_cli / 'invocation.json').read_text())
        assert args[args.index('--tenant') + 1] == TENANT
        assert args[args.index('--resource') + 1].rstrip('/') == 'https://management.azure.com'
        # A logged-out host must not silently fall back to another identity/cache.
        (local_cli / 'test-login.json').unlink()
        with pytest.raises(CredentialUnavailableError, match='az login'):
            credential.get_token('https://management.azure.com/.default')
    finally:
        credential.close()


def test_managed_identity_never_invokes_developer_cli(local_cli, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_CLOUD_IDENTITY', 'managed_identity')
    credential = azure_credential({'tenant_id': TENANT}, settings={'azure_access': 'direct'})
    try:
        assert type(credential).__name__ == 'ManagedIdentityCredential'
        assert not (local_cli / 'invocation.json').exists()
    finally:
        credential.close()
