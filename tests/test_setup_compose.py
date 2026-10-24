import hashlib
import json
import secrets
import stat

import pytest

import scripts.setup_compose as setup

TOKENS = ['CLOUDSAVER_IDENTITY_TOKEN_' + c for c in ('GATEWAY', 'TENANT', 'SCANNER', 'ANALYTICS', 'NOTIFICATION', 'AGENT')]
PLATFORM = ['TOKEN_DB_PASSWORD', 'IDENTITY_DB_OWNER_PASSWORD', 'IDENTITY_DB_APP_PASSWORD', 'CLOUDSAVER_KEY_PEPPER',
            'CLOUDSAVER_KEY_PEPPER_VERSION', 'CLOUDSAVER_IDENTITY_CALLERS', 'CLOUDSAVER_IDENTITY_TOKEN_PORTAL',
            'CLOUDSAVER_PORTAL_AUTH', 'CLOUDSAVER_OPERATOR_KEY_SHA256', 'CLOUDSAVER_IDENTITY_REDIS_URL',
            'STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET', 'STRIPE_PRICE_TIERS', 'CLOUDSAVER_STRIPE_CUSTOMERS',
            'CLOUDSAVER_BILLING_RETURN_URL', 'BILLING_RETURN_URL']


@pytest.fixture
def env(tmp_path, monkeypatch):
    target = tmp_path / '.env'
    monkeypatch.setattr(setup, 'path', target)
    monkeypatch.setattr(setup, 'platform_env', tmp_path / 'platform' / '.env')
    return target


def values(target):
    return dict(line.split('=', 1) for line in target.read_text().splitlines() if '=' in line and not line.startswith('#'))


def mode(target):
    return stat.S_IMODE(target.stat().st_mode)


def test_blank_agent_caller_placeholder_is_provisioned_without_printing_secret(env,capsys):
    env.write_text('POSTGRES_PASSWORD=synthetic\nCLOUDSAVER_IDENTITY_TOKEN_AGENT=\n')
    setup.add_identity()
    configured=values(env)
    assert len(configured['CLOUDSAVER_IDENTITY_TOKEN_AGENT'])>=32
    assert env.read_text().count('CLOUDSAVER_IDENTITY_TOKEN_AGENT=')==1
    assert configured['CLOUDSAVER_IDENTITY_TOKEN_AGENT'] not in capsys.readouterr().out


@pytest.mark.parametrize('blank', ['', "''", '"" # copied template'])
def test_init_db_passwords_repairs_blanks_without_rotating_or_disclosing_credentials(env, capsys, blank):
    existing = secrets.token_hex(32)
    env.write_text(f'# keep this configuration\nPOSTGRES_PASSWORD={existing}\nCLOUDSAVER_DB_PASSWORD={blank}\nCLOUDSAVER_TENANTS=[]\n')
    setup.init_db_passwords()
    configured = values(env)
    assert configured['POSTGRES_PASSWORD'] == existing
    assert len(configured['CLOUDSAVER_DB_PASSWORD']) == 64
    int(configured['CLOUDSAVER_DB_PASSWORD'], 16)
    assert mode(env) == 0o600 and '# keep this configuration' in env.read_text()
    output = capsys.readouterr().out
    assert existing not in output and configured['CLOUDSAVER_DB_PASSWORD'] not in output
    before = env.read_bytes()
    setup.init_db_passwords()
    assert env.read_bytes() == before and 'No file was changed' in capsys.readouterr().out


def test_init_db_passwords_adds_absent_keys_and_refuses_ambiguous_existing_values(env):
    env.write_text('CLOUDSAVER_TENANTS=[]\n')
    setup.init_db_passwords()
    assert all(len(values(env)[name]) == 64 for name in ('POSTGRES_PASSWORD', 'CLOUDSAVER_DB_PASSWORD'))
    env.write_text('POSTGRES_PASSWORD=original\nPOSTGRES_PASSWORD=\n')
    before = env.read_bytes()
    with pytest.raises(SystemExit, match='Duplicate'):
        setup.init_db_passwords()
    assert env.read_bytes() == before


def test_init_db_passwords_requires_an_existing_env(env):
    with pytest.raises(SystemExit, match='No .env found'):
        setup.init_db_passwords()
    assert not env.exists()


def test_create_generates_only_cloudsaver_settings_and_prints_digests(env, capsys):
    setup.create()
    created = values(env)
    assert mode(env) == 0o600
    assert set(TOKENS) <= set(created) and created['CLOUDSAVER_IDENTITY_URL'] == 'http://identity-service:8005'
    assert not [name for name in created if setup.is_platform_key(name)]
    assert 'CLOUDSAVER_REGISTRY_EXPORT_PASSWORD' not in created
    out = capsys.readouterr().out
    for name in TOKENS:
        assert created[name] not in out
    digests = json.loads(out.split('PLATFORM_IDENTITY_CALLERS): ', 1)[1].splitlines()[0])
    assert digests['gateway'] == hashlib.sha256(created['CLOUDSAVER_IDENTITY_TOKEN_GATEWAY'].encode()).hexdigest()
    assert set(digests) == {'gateway', 'tenant', 'scanner', 'analytics', 'notification', 'agent'}
    with pytest.raises(SystemExit):
        setup.create()


def test_add_identity_adds_only_missing_tokens(env, capsys):
    existing = secrets.token_urlsafe(32)
    env.write_text(f'POSTGRES_PASSWORD=x\nCLOUDSAVER_IDENTITY_TOKEN_GATEWAY={existing}\n')
    setup.add_identity()
    updated = values(env)
    assert updated['CLOUDSAVER_IDENTITY_TOKEN_GATEWAY'] == existing and set(TOKENS) <= set(updated)
    assert mode(env) == 0o600
    out = capsys.readouterr().out
    assert 'CLOUDSAVER_IDENTITY_TOKEN_GATEWAY' not in out.split('Added to .env: ', 1)[1].splitlines()[0]
    assert not any(updated[name] in out for name in TOKENS)
    setup.add_identity()
    assert 'No file was changed' in capsys.readouterr().out


def test_cutover_needs_the_caller_tokens(env):
    env.write_text('POSTGRES_PASSWORD=x\n')
    with pytest.raises(SystemExit):
        setup.cutover()
    setup.add_identity()
    setup.cutover()
    assert values(env)['CLOUDSAVER_DIRECTORY_MODE'] == 'cutover'


def legacy(env):
    lines = ['POSTGRES_PASSWORD=keep-me', 'CLOUDSAVER_DB_PASSWORD=keep-me-too', '# a comment stays']
    lines += [f'{name}={secrets.token_urlsafe(16)}' for name in TOKENS + PLATFORM]
    env.write_text('\n'.join(lines) + '\n')
    return env.read_text()


def test_prune_refuses_without_a_platform_pepper(env):
    before = legacy(env)
    with pytest.raises(SystemExit) as missing:
        setup.prune_platform()
    assert 'PLATFORM_KEY_PEPPER' in str(missing.value)
    setup.platform_env.parent.mkdir()
    setup.platform_env.write_text('PLATFORM_DATABASE_URL=placeholder\n')
    with pytest.raises(SystemExit):
        setup.prune_platform()
    assert env.read_text() == before


def test_prune_removes_platform_settings_and_prints_names_only(env, capsys):
    legacy(env)
    removed_values = {name: value for name, value in values(env).items() if name in PLATFORM}
    setup.platform_env.parent.mkdir()
    setup.platform_env.write_text('PLATFORM_KEY_PEPPER=placeholder\n')
    env.chmod(0o644)
    setup.prune_platform()
    kept = values(env)
    assert mode(env) == 0o600
    assert not set(PLATFORM) & set(kept) and set(TOKENS) <= set(kept)
    assert kept['POSTGRES_PASSWORD'] == 'keep-me' and '# a comment stays' in env.read_text()
    out = capsys.readouterr().out
    assert all(name in out for name in PLATFORM)
    assert not any(value in out for value in removed_values.values())
    setup.prune_platform()
    assert 'No platform settings found' in capsys.readouterr().out
