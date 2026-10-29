import json
from pathlib import Path
import shutil

import pytest

from scripts import start_stack


def setup_root(tmp_path,monkeypatch):
    source=start_stack.ROOT
    for name in ('scripts/setup_compose.py','platform/scripts/setup_platform.py'):
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,target)
    monkeypatch.setattr(start_stack,'ROOT',tmp_path)
    home=tmp_path/'.env.local-stack';home.mkdir(mode=0o700)
    return home


def test_first_run_and_repeat_preserve_credentials(tmp_path,monkeypatch,capsys):
    home=setup_root(tmp_path,monkeypatch)
    env=tmp_path/'.env'
    tenant=start_stack.prepare_settings(env,home)
    paths=[env,tmp_path/'platform/.env',home/'operator-login.txt',home/'runtime.env',home/'settings.json']
    before={p:p.read_bytes() for p in paths}
    assert capsys.readouterr().out==''
    assert start_stack.prepare_settings(env,home)==tenant
    assert all(p.read_bytes()==content for p,content in before.items())
    assert all(p.stat().st_mode&0o777==0o600 for p in paths)
    runtime=start_stack.env_values(home/'runtime.env')
    grants=json.loads(runtime['CLOUDSAVER_AGENT_WORKERS'])
    assert grants[0]['tenant_ids']==[tenant] and grants[0]['connector_ids']==[]
    assert runtime['CLOUDSAVER_AGENT_CONNECTORS']=='[]'


def test_refuse_production_configuration(tmp_path,monkeypatch):
    home=setup_root(tmp_path,monkeypatch)
    env=tmp_path/'.env';env.write_text('CLOUDSAVER_ENVIRONMENT=production\n')
    with pytest.raises(ValueError,match='development only'):start_stack.prepare_settings(env,home)
    assert not (tmp_path/'platform/.env').exists()


def test_start_orders_migrations_before_workers_and_waits_for_every_project(tmp_path,monkeypatch):
    monkeypatch.delenv('CODEX_PROXY_CERT',raising=False)
    home=setup_root(tmp_path,monkeypatch)
    stack=start_stack.Stack(tmp_path/'.env',home,180,no_build=True)
    stack.shared_network=lambda:None
    stack.license_configuration=lambda:None
    calls=[]
    stack.run=lambda args,**kwargs:calls.append(args)
    stack.keycloak=lambda tenant:calls.append(['keycloak-ready',tenant])
    stack.start('11111111-1111-4111-8111-111111111111')
    migration=next(i for i,c in enumerate(calls) if 'run' in c and c[-1]=='migrate')
    seed=next(i for i,c in enumerate(calls) if 'LOCAL_TENANT_ID=11111111-1111-4111-8111-111111111111' in c)
    final=next(i for i,c in enumerate(calls) if c[-5:]==['up','-d','--wait','--wait-timeout','180'] and 'scheduled' in c)
    assert calls.index(['keycloak-ready','11111111-1111-4111-8111-111111111111'])<migration<seed<final
    assert all('--wait' in c for c in calls if 'up' in c and 'platform-db' not in c)
    assert any('exec' in c and '/docker-entrypoint-initdb.d/00-identity.sh' in c for c in calls)
    assert '--profile' in calls[final] and 'agentic' in calls[final] and 'delivery' in calls[final]
    assert not any('down' in c or '--volumes' in c for c in calls)


def test_failure_stops_later_services(tmp_path,monkeypatch):
    import subprocess
    monkeypatch.delenv('CODEX_PROXY_CERT',raising=False)
    home=setup_root(tmp_path,monkeypatch)
    stack=start_stack.Stack(tmp_path/'.env',home,180,no_build=True)
    stack.shared_network=lambda:None
    stack.license_configuration=lambda:None
    calls=[]
    def fail(args,**kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1,args)
    stack.run=fail
    with pytest.raises(subprocess.CalledProcessError):stack.start('unused')
    assert len(calls)==1


def test_reuse_existing_internal_shared_network(tmp_path,monkeypatch):
    from subprocess import CompletedProcess
    home=setup_root(tmp_path,monkeypatch)
    stack=start_stack.Stack(tmp_path/'.env',home,180)
    stack.run=lambda args,**kwargs:CompletedProcess(args,0,stdout=json.dumps([{'Internal':True,'Labels':{}}]))
    stack.shared_network()
    override=json.loads((home/'platform-network.json').read_text())
    assert override['networks']['platform-link']=={'external':True,'internal':None}
    assert str(home/'platform-network.json') in stack.compose('platform')


def test_reject_public_shared_network(tmp_path,monkeypatch):
    from subprocess import CompletedProcess
    home=setup_root(tmp_path,monkeypatch)
    stack=start_stack.Stack(tmp_path/'.env',home,180)
    stack.run=lambda args,**kwargs:CompletedProcess(args,0,stdout=json.dumps([{'Internal':False}]))
    with pytest.raises(ValueError,match='must be internal'):stack.shared_network()


def test_adopt_existing_keycloak_workspace_on_first_launcher_run(tmp_path,monkeypatch):
    home=setup_root(tmp_path,monkeypatch)
    config=home/'config';config.mkdir()
    tid='11111111-1111-4111-8111-111111111111'
    (config/'cloudsaver.env').write_text('CLOUDSAVER_KEYCLOAK_BINDINGS='+json.dumps([{'tenant_id':tid}])+'\n')
    assert start_stack.prepare_settings(tmp_path/'.env',home)==tid


def test_unified_env_contains_generated_secrets_without_logging(tmp_path,monkeypatch,capsys):
    import secrets
    home=setup_root(tmp_path,monkeypatch)
    env=tmp_path/'.env'
    start_stack.prepare_settings(env,home)
    config=home/'config';config.mkdir()
    admin=secrets.token_urlsafe(32)+"'"+'$literal'
    verifier=secrets.token_urlsafe(32)
    (config/'keycloak.env').write_text('KEYCLOAK_ADMIN_PASSWORD='+admin+'\n')
    (config/'cloudsaver.env').write_text('CLOUDSAVER_KEYCLOAK_SECRET_PRIMARY='+verifier+'\n')
    target=start_stack.sync_secrets(env,home)
    values=start_stack.env_values(target)
    assert values['KEYCLOAK_ADMIN_PASSWORD']==admin
    assert values['KEYCLOAK_ADMIN_USER']=='bootstrap-admin'
    assert values['CLOUDSAVER_KEYCLOAK_SECRET_PRIMARY']==verifier
    assert values['POSTGRES_PASSWORD'] and values['PLATFORM_DB_PASSWORD']
    assert values['PLATFORM_OPERATOR_ACCESS_KEY'] and values['CLOUDSAVER_AGENT_WORKER_TOKEN']
    assert values['CLOUDSAVER_STACK_HOME']==str(home)
    assert target.stat().st_mode&0o777==0o600
    start_stack.prepare_settings(env,home)
    start_stack.sync_secrets(env,home)
    assert start_stack.env_values(target)==values
    platform=start_stack.env_values(tmp_path/'platform/.env')
    import hashlib
    assert json.loads(platform['PLATFORM_IDENTITY_CALLERS'])['gateway']==hashlib.sha256(values['CLOUDSAVER_IDENTITY_TOKEN_GATEWAY'].encode()).hexdigest()
    assert capsys.readouterr().out==''


def test_unified_env_refuses_symlink_target(tmp_path,monkeypatch):
    home=setup_root(tmp_path,monkeypatch)
    other=tmp_path/'other';other.write_text('preserve')
    (tmp_path/'.env').symlink_to(other)
    with pytest.raises(ValueError,match='symlink'):start_stack.sync_secrets(tmp_path/'.env',home)
    assert other.read_text()=='preserve'


def test_signing_key_generated_once_and_mounted_only_in_issuer(tmp_path,monkeypatch):
    import shutil
    if not shutil.which('openssl'):pytest.skip('OpenSSL required')
    home=setup_root(tmp_path,monkeypatch)
    env=tmp_path/'.env';start_stack.prepare_settings(env,home)
    stack=start_stack.Stack(env,home,180,auth_mode='license')
    stack.license_configuration()
    original=(home/'license-private.pem').read_bytes()
    config=json.loads((home/'platform-license.json').read_text())
    assert set(config['services'])=={'identity-service'}
    assert config['services']['identity-service']['volumes']==[str(home/'license-private.pem')+':/run/license-private.pem:ro']
    values=start_stack.env_values(env)
    assert values['CLOUDSAVER_AUTH_MODE']=='license'
    assert 'PRIVATE KEY' not in values['CLOUDSAVER_LICENSE_PUBLIC_KEYS']
    assert 'PUBLIC KEY' in values['CLOUDSAVER_LICENSE_PUBLIC_KEYS']
    stack.license_configuration()
    assert (home/'license-private.pem').read_bytes()==original
    (home/'license-private.pem').unlink()
    with pytest.raises(ValueError,match='never silently rotates'):stack.license_configuration()
