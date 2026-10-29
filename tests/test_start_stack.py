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
