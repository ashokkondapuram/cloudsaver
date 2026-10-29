"""Start the complete local development stack; requires Docker Compose, Python 3 and OpenSSL."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import ssl
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'cloudsaver-python:1.7.0'
PYTHON_SERVICES = ('api-gateway','scanner-service','governance-monitor','agent-gateway',
                   'data-retention-worker','billing-sync-worker','observability-worker',
                   'scan-worker','delivery-dispatcher','scan-scheduler')


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'w') as handle:
        handle.write(text)


def env_values(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        name,value = line.split('=',1)
        # Generated setup files use only literal values, not shell expansion.
        if value[:1] in ('"',"'"):
            parts=shlex.split(value,comments=True)
            value=parts[0] if parts else ''
        result[name.strip()]=value
    return result


def module(path, name):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def prepare_settings(env_file, home):
    setup=module(ROOT/'scripts/setup_compose.py','local_compose_setup')
    setup.path=env_file
    if not env_file.exists():
        with contextlib.redirect_stdout(io.StringIO()):setup.create()
    if env_values(env_file).get('CLOUDSAVER_ENVIRONMENT','development') != 'development':
        raise ValueError('This launcher is for development only; use your reviewed deployment for other environments')
    platform=module(ROOT/'platform/scripts/setup_platform.py','local_platform_setup')
    if not platform.path.exists():
        captured=io.StringIO()
        with contextlib.redirect_stdout(captured):platform.create()
        private_write(home/'operator-login.txt',captured.getvalue())
    with contextlib.redirect_stdout(io.StringIO()):platform.add_callers(env_file)
    settings=home/'settings.json'
    if not settings.exists():
        seed=json.loads(env_values(env_file).get('CLOUDSAVER_TENANTS','[]'))
        existing_binding=home/'config/cloudsaver.env'
        if existing_binding.exists():
            tenant_id=json.loads(env_values(existing_binding)['CLOUDSAVER_KEYCLOAK_BINDINGS'])[0]['tenant_id']
        else:tenant_id=seed[0]['tenant_id'] if seed else str(uuid4())
        private_write(settings,json.dumps({'tenant_id':tenant_id}))
    if not (home/'runtime.env').exists():
        worker=secrets.token_urlsafe(48)
        tenant_id=json.loads(settings.read_text())['tenant_id']
        grants=[dict(id='local-worker',token_sha256=hashlib.sha256(worker.encode()).hexdigest(),tenant_ids=[tenant_id],connector_ids=[])]
        values={'CLOUDSAVER_AGENT_ENABLED':'true','CLOUDSAVER_AGENT_WORKER_TOKEN':worker,
                'CLOUDSAVER_AGENT_TENANT_IDS':json.dumps([tenant_id]),'CLOUDSAVER_AGENT_WORKERS':json.dumps(grants),
                'CLOUDSAVER_AUTO_BILLING_SYNC':'false','CLOUDSAVER_COMMITMENT_SYNC':'false',
                'CLOUDSAVER_OBSERVABILITY_SYNC':'false','CLOUDSAVER_SCHEDULED_SCANS':'false',
                'CLOUDSAVER_AGENT_CONNECTORS':'[]','CLOUDSAVER_ENGINEERING_CURSOR_KEY':secrets.token_urlsafe(48),
                'CLOUDSAVER_DIRECTORY_MODE':'registry','CLOUDSAVER_KEY_VERIFIER':'local'}
        private_write(home/'runtime.env',''.join(k+'='+v+'\n' for k,v in values.items()))
    return json.loads(settings.read_text())['tenant_id']


class Stack:
    def __init__(self, env_file, home, timeout, no_build=False):
        self.env_file,self.home,self.timeout,self.no_build=env_file,home,timeout,no_build
        self.environment=dict(os.environ,COMPOSE_PARALLEL_LIMIT='1',BUILDX_CONFIG=str(home/'buildx'))
        self.environment['KEYCLOAK_CA_BUNDLE']=str(home/'ca-bundle.pem')

    def run(self,args,**kwargs):
        return subprocess.run(args,cwd=ROOT,env=self.environment,check=True,**kwargs)

    def compose(self,kind,connected=True):
        if kind=='platform':
            args=['docker','compose','--project-directory',str(ROOT/'platform'),'--env-file',str(ROOT/'platform/.env'),'-f',str(ROOT/'platform/compose.yaml')]
        elif kind=='keycloak':
            args=['docker','compose','--env-file',str(self.home/'config/keycloak.env'),'-f',str(ROOT/'deploy/keycloak/compose.yaml'),'-f',str(self.home/'keycloak-network.json')]
        else:
            args=['docker','compose','--env-file',str(self.env_file),'--env-file',str(self.home/'runtime.env')]
            if connected:args+=['--env-file',str(self.home/'config/cloudsaver.env')]
            args+=['-f',str(ROOT/'compose.yaml')]
            if connected:args+=['-f',str(ROOT/'deploy/keycloak/cloudsaver.override.yaml')]
            args+=['--profile','scheduled','--profile','agentic','--profile','delivery']
        if kind=='platform' and (self.home/'platform-network.json').exists():
            args+=['-f',str(self.home/'platform-network.json')]
        if (self.home/(kind+'-build.json')).exists():args+=['-f',str(self.home/(kind+'-build.json'))]
        return args

    def build_configuration(self):
        ca=os.environ.get('CODEX_PROXY_CERT')
        if not ca:return
        if not Path(ca).is_file():raise ValueError('Configured proxy CA file does not exist')
        for kind,services in [('platform',['identity-service','platform-portal']),('app',list(PYTHON_SERVICES)+['migrate','web-dashboard','agent-worker'])]:
            data={'secrets':{'proxy_ca':{'file':str(Path(ca).resolve())}},'services':{s:{'build':{'secrets':['proxy_ca']}} for s in services}}
            (self.home/(kind+'-build.json')).write_text(json.dumps(data))

    def keycloak(self,tenant_id):
        config=self.home/'config'
        if not config.exists():
            tls=self.home/'tls';tls.mkdir(exist_ok=True)
            if not (tls/'key.pem').exists():
                self.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','30','-keyout',str(tls/'key.pem'),'-out',str(tls/'cert.pem'),'-subj','/CN=keycloak.localhost','-addext','subjectAltName=DNS:keycloak.localhost'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                (tls/'key.pem').chmod(0o644) # parent directory is owner-only; container must read the bind mount
            license_record=dict(schema_version=1,enabled=True,expires_at=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),plan=dict(code='STARTER',name='Local trial',entitlements_version=1,billing_state='none',entitlements=dict(max_subscriptions=2,max_resources_per_scan=250,allowed_providers=['azure','aws','gcp','kubernetes'],allowed_scan_frequencies=['manual'],can_export_terraform=False,can_use_keyvault=False,can_dispatch_automated_alerts=False,can_use_ai_advisory=False,retention_days=7)))
            if not (self.home/'license.json').exists():private_write(self.home/'license.json',json.dumps(license_record))
            uid,gid=getattr(os,'getuid',lambda:1000)(),getattr(os,'getgid',lambda:1000)()
            code="""import os
from scripts.setup_keycloak import generate
import json
try:
 generate('/bootstrap/config','https://keycloak.localhost:8443',os.environ['LOCAL_TENANT_ID'],json.load(open('/bootstrap/license.json')),'/bootstrap/tls/cert.pem','/bootstrap/tls/key.pem')
finally:
 for root,dirs,files in os.walk('/bootstrap'):
  os.chown(root,int(os.environ['LOCAL_UID']),int(os.environ['LOCAL_GID']))
  for name in files:os.chown(os.path.join(root,name),int(os.environ['LOCAL_UID']),int(os.environ['LOCAL_GID']))
"""
            self.run(['docker','run','--rm','--user','0:0','-e','LOCAL_TENANT_ID='+tenant_id,'-e','LOCAL_UID='+str(uid),'-e','LOCAL_GID='+str(gid),'-v',str(self.home)+':/bootstrap',IMAGE,'python','-c',code])
            values=env_values(config/'keycloak.env')
            values.update(KEYCLOAK_IMPORT_DIR=str(config/'import'),KEYCLOAK_TLS_CERT=str(tls/'cert.pem'),KEYCLOAK_TLS_KEY=str(tls/'key.pem'))
            target=config/'keycloak.env';target.write_text(''.join(k+"='"+v+"'\n" for k,v in values.items()))
        if not all((config/f).is_file() for f in ('keycloak.env','cloudsaver.env','import/realm.json')):
            raise ValueError('Keycloak setup is incomplete; inspect the private stack directory before retrying')
        roots=ssl.create_default_context().get_ca_certs(binary_form=True)
        cert=Path(env_values(config/'keycloak.env')['KEYCLOAK_TLS_CERT'])
        (self.home/'ca-bundle.pem').write_text(''.join(ssl.DER_cert_to_PEM_cert(c) for c in roots)+cert.read_text())
        network={'services':{'keycloak':{'networks':{'private':{},'egress':{},'application':{'aliases':['keycloak.localhost']}}}},'networks':{'application':{'name':'cloudsaver_default','external':True}}}
        (self.home/'keycloak-network.json').write_text(json.dumps(network))
        self.run(self.compose('keycloak')+['up','-d','--wait','--wait-timeout',str(self.timeout)])

    def shared_network(self):
        target=self.home/'platform-network.json'
        try:
            result=self.run(['docker','network','inspect','platform-link'],capture_output=True,text=True)
        except subprocess.CalledProcessError:
            target.unlink(missing_ok=True)
            return # platform Compose creates its private shared network on first boot
        info=json.loads(result.stdout)[0]
        if not info.get('Internal'):
            raise ValueError('Existing platform-link network must be internal')
        labels=info.get('Labels') or {}
        if labels.get('com.docker.compose.project')!='platform':
            target.write_text(json.dumps({'networks':{'platform-link':{'external':True,'internal':None}}}))
        else:target.unlink(missing_ok=True)

    def start(self,tenant_id):
        self.shared_network()
        self.build_configuration()
        if not self.no_build:
            # Serialize builds to bound peak disk/RAM use on Docker Desktop.
            for service in ('scanner-service','web-dashboard','postgres','agent-worker'):
                self.run(self.compose('app',False)+['build',service])
            for service in ('identity-service','platform-portal','platform-db','identity-egress'):
                self.run(self.compose('platform')+['build',service])
        platform=self.compose('platform')
        self.run(platform+['up','-d','platform-db','platform-redis','identity-egress'])
        # Repair an interrupted initdb without resetting existing role passwords.
        wait='i=0; until pg_isready -h 127.0.0.1 -U postgres -d postgres >/dev/null; do i=$((i+1)); [ "$i" -lt 60 ] || exit 1; sleep 1; done'
        self.run(platform+['exec','-T','platform-db','sh','-ec',wait])
        self.run(platform+['exec','-T','--user','postgres','platform-db','/docker-entrypoint-initdb.d/00-identity.sh'])
        self.run(platform+['up','-d','--wait','--wait-timeout',str(self.timeout)])
        self.run(self.compose('app',False)+['up','-d','--wait','--wait-timeout',str(self.timeout),'postgres','redis'])
        self.keycloak(tenant_id)
        app=self.compose('app')
        self.run(app+['run','--rm','--no-deps','migrate'])
        seed="""import hashlib,secrets,os
from app.config import Settings
s=Settings.load();tid=os.environ['LOCAL_TENANT_ID']
if not s.registry.get(tid):s.registry.create(dict(tenant_id=tid,name='Local workspace',subscription_ids=[],api_key_sha256=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),plan_tier='STARTER'), 'local-stack-bootstrap')
print('Local workspace ready; no cloud scope was authorized.')
"""
        self.run(app+['run','--rm','--no-deps','-e','LOCAL_TENANT_ID='+tenant_id,'scanner-service','python','-c',seed])
        self.run(app+['up','-d','--wait','--wait-timeout',str(self.timeout)])
        self.run(self.compose('platform')+['ps'])
        self.run(self.compose('keycloak')+['ps'])
        self.run(app+['ps'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--state-dir',type=Path,default=ROOT/'.env.local-stack')
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--no-build',action='store_true',help='Use previously built images')
    args=parser.parse_args()
    if args.timeout<30:parser.error('Timeout must be at least 30 seconds')
    for command in ('docker','openssl'):
        if not shutil.which(command):parser.error('Install '+command+' before starting')
    home=args.state_dir.resolve();home.mkdir(parents=True,exist_ok=True,mode=0o700);home.chmod(0o700)
    try:
        stack=Stack(args.env_file.resolve(),home,args.timeout,args.no_build)
        stack.run(['docker','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        stack.run(['docker','compose','version'],stdout=subprocess.DEVNULL)
        tenant_id=prepare_settings(args.env_file.resolve(),home)
        stack.start(tenant_id)
    except (subprocess.CalledProcessError,ValueError,OSError) as error:
        print('Startup stopped: '+str(error)+'. Existing volumes and credentials were retained.',file=sys.stderr)
        return 1
    print('All stack health checks passed. Dashboard: http://127.0.0.1:3000')
    print('Platform portal: http://127.0.0.1:3100 | Keycloak: https://keycloak.localhost:8443/admin/')
    print('Private credentials and configuration: '+str(home))
    print('Local certificate/trial license expire after 30 days; reruns do not silently renew them.')
    return 0

if __name__=='__main__':raise SystemExit(main())
