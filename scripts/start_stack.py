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
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'cloudsaver-python:1.8.1'
PYTHON_SERVICES = ('api-gateway','scanner-service','governance-monitor','agent-gateway',
                   'data-retention-worker','billing-sync-worker','observability-worker',
                   'scan-worker','delivery-dispatcher','scan-scheduler')


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'w') as handle:
        handle.write(text)


def env_values(path):
    path = Path(path)
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        name,value = line.split('=',1)
        # Generated setup files use only literal values, not shell expansion.
        if value.startswith("'") and value.endswith("'"):
            value=value[1:-1].replace("\\'", "'")
        elif value[:1] in ('"',"'"):
            parts=shlex.split(value,comments=True)
            value=parts[0] if parts else ''
        result[name.strip()]=value
    return result


def name_of(line):
    if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
        return None
    return line.split('=', 1)[0].strip()


KEYCLOAK_ENV_PREFIXES = ('KEYCLOAK_', 'CLOUDSAVER_KEYCLOAK_')


def prune_keycloak_env(path):
    """Drop Keycloak connection settings from the root .env in workspace-key dev mode."""
    path = Path(path)
    if not path.exists():
        return
    kept = [line for line in path.read_text().splitlines()
            if not (name := name_of(line)) or not name.startswith(KEYCLOAK_ENV_PREFIXES)]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('\n'.join(kept) + ('\n' if kept else ''))


def patch_env_file(path, updates):
    """Update keys in the user's .env without replacing unrelated settings."""
    path = Path(path)
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    patched = []
    for line in lines:
        key = name_of(line)
        if key in updates:
            patched.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            patched.append(line)
    for key, value in updates.items():
        if key not in seen:
            patched.append(f'{key}={value}')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('\n'.join(patched) + ('\n' if patched else ''))


def apply_workspace_local_auth(env_file):
    patch_env_file(env_file, {
        'CLOUDSAVER_AUTH_MODE': 'workspace',
        'CLOUDSAVER_DIRECTORY_MODE': 'registry',
        'CLOUDSAVER_KEY_VERIFIER': 'identity',
    })
    prune_keycloak_env(env_file)


def sync_secrets(env_file, home, auth_mode=None, local_creds=True):
    """Collect generated runtime credentials in the ignored root .env, never in an image."""
    target=ROOT/'.env'
    if target.is_symlink():raise ValueError('Refusing to write secrets through a symlink')
    env_file = Path(env_file)
    if local_creds:
        patch_env_file(env_file, {'CLOUDSAVER_STACK_HOME': str(home)})
        selected = auth_mode or (env_values(env_file).get('CLOUDSAVER_AUTH_MODE') if env_file.exists() else None)
        if selected == 'license':
            patch_env_file(env_file, {'CLOUDSAVER_AUTH_MODE': 'license'})
            license_env = home / 'license.env'
            if license_env.exists():
                license_values = {k: v for k, v in env_values(license_env).items() if k.startswith('CLOUDSAVER_')}
                if license_values:
                    patch_env_file(env_file, license_values)
        else:
            apply_workspace_local_auth(env_file)
        return env_file
    selected=auth_mode or (env_values(env_file).get('CLOUDSAVER_AUTH_MODE') if env_file.exists() else None)
    values={}
    sources=(target,env_file,ROOT/'platform/.env',home/'runtime.env',
             home/'config/keycloak.env',home/'config/cloudsaver.env',home/'license.env')
    for source in sources:
        if source.exists():values.update(env_values(source))
    values['CLOUDSAVER_STACK_HOME']=str(home)
    if selected in ('license','keycloak','workspace'):values['CLOUDSAVER_AUTH_MODE']=selected
    if (home/'config/keycloak.env').exists():
        values.setdefault('KEYCLOAK_ADMIN_USER','bootstrap-admin')
    operator=home/'operator-login.txt'
    if operator.exists():
        prefix='Operator access key (shown once): '
        for line in operator.read_text().splitlines():
            if line.startswith(prefix):values['PLATFORM_OPERATOR_ACCESS_KEY']=line[len(prefix):]
    user=home/'config/user-credentials.json'
    if user.exists():
        credential=json.loads(user.read_text())
        values['CLOUDSAVER_LOCAL_ADMIN_USERNAME']=credential['username']
        values['CLOUDSAVER_LOCAL_ADMIN_PASSWORD']=credential['password']
    if any('\n' in v or '\r' in v for v in values.values()):
        raise ValueError('Use file references for multiline secrets')
    text='# Generated local runtime settings and secrets. Keep private; never commit.\n'
    text+='\n'.join(k+"='"+v.replace("'", "\\'")+"'" for k,v in sorted(values.items()))+'\n'
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=target.parent,prefix='.env-secrets-',delete=False) as handle:
            temporary=Path(handle.name)
            os.fchmod(handle.fileno(),0o600)
            handle.write(text)
        os.replace(temporary,target)
    finally:
        if temporary:temporary.unlink(missing_ok=True)
    return target


def module(path, name):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def resolve_auth_mode(auth_mode, env_file, local_creds=True):
    if auth_mode in ('license','keycloak','workspace'):
        return auth_mode
    selected=env_values(env_file).get('CLOUDSAVER_AUTH_MODE') if env_file.exists() else None
    if selected in ('license','keycloak','workspace'):
        return selected
    return 'workspace' if local_creds else 'keycloak'


def workspace_cloudsaver_env():
    return ('CLOUDSAVER_AUTH_MODE=workspace\nCLOUDSAVER_DIRECTORY_MODE=registry\n'
            'CLOUDSAVER_KEY_VERIFIER=identity\n')


def ensure_runtime_key_verifier(home, verifier):
    path=home/'runtime.env'
    if not path.exists():
        return
    lines=path.read_text().splitlines()
    key='CLOUDSAVER_KEY_VERIFIER='
    replaced=False
    for index,line in enumerate(lines):
        if line.startswith(key):
            lines[index]=key+verifier
            replaced=True
            break
    if not replaced:
        lines.append(key+verifier)
    path.write_text('\n'.join(lines)+('\n' if lines else ''))
    path.chmod(0o600)


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
    # The unified file quotes values; register the decoded token, not its quotes.
    platform.parse=env_values
    with contextlib.redirect_stdout(io.StringIO()):platform.add_callers(env_file)
    settings=home/'settings.json'
    if not settings.exists():
        seed=json.loads(env_values(env_file).get('CLOUDSAVER_TENANTS','[]'))
        tenant_id=seed[0]['tenant_id'] if seed else str(uuid4())
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
                'CLOUDSAVER_DIRECTORY_MODE':'registry','CLOUDSAVER_KEY_VERIFIER':'identity'}
        private_write(home/'runtime.env',''.join(k+'='+v+'\n' for k,v in values.items()))
    return json.loads(settings.read_text())['tenant_id']


def operator_access_key(home):
    operator = home / 'operator-login.txt'
    if not operator.exists():
        return None
    prefix = 'Operator access key (shown once): '
    for line in operator.read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


class Stack:
    def __init__(self, env_file, home, timeout, no_build=False, auth_mode=None, local_creds=True):
        self.env_file,self.home,self.timeout,self.no_build=env_file,home,timeout,no_build
        self.local_creds=local_creds
        self.auth_mode=resolve_auth_mode(auth_mode,env_file,local_creds)
        self.environment=dict(os.environ,COMPOSE_PARALLEL_LIMIT='1',BUILDX_CONFIG=str(home/'buildx'))
        if self.auth_mode == 'keycloak':
            self.environment['KEYCLOAK_CA_BUNDLE']=str(home/'ca-bundle.pem')
        self.environment['CLOUDSAVER_AUTH_MODE']=self.auth_mode

    def run(self,args,**kwargs):
        return subprocess.run(args,cwd=ROOT,env=self.environment,check=True,**kwargs)

    def compose(self,kind,connected=True):
        if kind=='platform':
            args=['docker','compose','--project-directory',str(ROOT/'platform'),'--env-file',str(ROOT/'platform/.env'),'-f',str(ROOT/'platform/compose.yaml')]
        elif kind=='keycloak':
            args=['docker','compose','--env-file',str(self.home/'config/keycloak.env'),'-f',str(ROOT/'deploy/keycloak/compose.yaml'),'-f',str(self.home/'keycloak-network.json')]
        else:
            args=['docker','compose','--env-file',str(self.env_file)]
            if not self.local_creds:
                args+=['--env-file',str(self.home/'runtime.env')]
            if connected and self.auth_mode in ('keycloak','license') and not self.local_creds:
                args+=['--env-file',str(self.home/'config/cloudsaver.env')]
            args+=['-f',str(ROOT/'compose.yaml')]
            if connected and self.auth_mode in ('keycloak','license') and not self.local_creds:
                args+=['-f',str(ROOT/'deploy/keycloak/cloudsaver.override.yaml')]
            args+=['--profile','scheduled','--profile','agentic','--profile','delivery']
        if kind=='platform' and (self.home/'platform-network.json').exists():
            args+=['-f',str(self.home/'platform-network.json')]
        if kind=='platform' and (self.home/'platform-license.json').exists():
            args+=['-f',str(self.home/'platform-license.json')]
        if (self.home/(kind+'-build.json')).exists():args+=['-f',str(self.home/(kind+'-build.json'))]
        return args

    def license_configuration(self):
        private=self.home/'license-private.pem'
        metadata=self.home/'license-settings.json'
        if metadata.exists() and not private.exists():
            raise ValueError('Restore the licence signing key; startup never silently rotates it')
        if not private.exists():
            self.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(private)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            # Docker binds this individual file into the issuer; its host parent remains 0700.
            private.chmod(0o644)
        if not metadata.exists():private_write(metadata,json.dumps({'kid':str(uuid4())}))
        public=subprocess.check_output(['openssl','pkey','-in',str(private),'-pubout'],text=True)
        kid=json.loads(metadata.read_text())['kid']
        issuer='https://cloudsaver-platform.local'
        audience='cloudsaver'
        values={'PLATFORM_LICENSE_PRIVATE_KEY_FILE':'/run/license-private.pem','PLATFORM_LICENSE_KEY_ID':kid,
                'PLATFORM_LICENSE_ISSUER':issuer,'PLATFORM_LICENSE_AUDIENCE':audience,
                'CLOUDSAVER_LICENSE_ISSUER':issuer,'CLOUDSAVER_LICENSE_AUDIENCE':audience,
                'CLOUDSAVER_LICENSE_PUBLIC_KEYS':json.dumps({kid:public}),
                'PLATFORM_LICENSE_PRIVATE_KEY_HOST_FILE':str(private)}
        target=self.home/'license.env'
        if not target.exists():private_write(target,'')
        target.write_text(''.join(k+"='"+v+"'\n" for k,v in values.items()))
        self.environment.update({k:v for k,v in values.items() if k.startswith('CLOUDSAVER_')})
        config={'services':{'identity-service':{'volumes':[str(private)+':/run/license-private.pem:ro'],
                'environment':{k:v for k,v in values.items() if k.startswith('PLATFORM_LICENSE_') and not k.endswith('HOST_FILE')}}}}
        (self.home/'platform-license.json').write_text(json.dumps(config))
        sync_secrets(self.env_file,self.home,self.auth_mode,self.local_creds)

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
        sync_secrets(self.env_file,self.home,self.auth_mode,self.local_creds)
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

    def configure_cloudsaver_auth(self):
        if self.local_creds:
            return
        config=self.home/'config'
        config.mkdir(parents=True,exist_ok=True)
        if self.auth_mode=='workspace':
            (config/'cloudsaver.env').write_text(workspace_cloudsaver_env())
            runtime = self.home / 'runtime.env'
            if not runtime.exists():
                private_write(runtime, workspace_cloudsaver_env())
            else:
                ensure_runtime_key_verifier(self.home, 'identity')
            sync_secrets(self.env_file, self.home, self.auth_mode, self.local_creds)
        elif self.auth_mode=='license':
            binding=config/'cloudsaver.env'
            if binding.exists():
                values=env_values(binding)
                values['CLOUDSAVER_AUTH_MODE']='license'
                binding.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))

    def start(self,tenant_id):
        self.shared_network()
        self.license_configuration()
        self.configure_cloudsaver_auth()
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
        if self.auth_mode=='keycloak':
            self.keycloak(tenant_id)
        app=self.compose('app')
        self.run(app+['run','--rm','--no-deps','migrate'])
        operator_key = operator_access_key(self.home)
        tenants_raw = env_values(self.env_file).get('CLOUDSAVER_TENANTS', '[]')
        if operator_key and tenants_raw.strip() not in ('', '[]'):
            self.run(app+['run','--rm','--no-deps',
                          '-e','LOCAL_OPERATOR_KEY='+operator_key,
                          '-e','LOCAL_TENANT_CONFIG='+tenants_raw,
                          'scanner-service','python','-m','scripts.bootstrap_local_identity'])
        else:
            seed="""import hashlib,secrets,os
from app.config import Settings
s=Settings.load();tid=os.environ['LOCAL_TENANT_ID']
if not s.registry.get(tid):s.registry.create(dict(tenant_id=tid,name='Local workspace',subscription_ids=[],api_key_sha256=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),plan_tier='STARTER'), 'local-stack-bootstrap')
print('Local workspace ready; no cloud scope was authorized.')
"""
            self.run(app+['run','--rm','--no-deps','-e','LOCAL_TENANT_ID='+tenant_id,'scanner-service','python','-c',seed])
        self.run(app+['up','-d','--wait','--wait-timeout',str(self.timeout)])
        self.run(self.compose('platform')+['ps'])
        if self.auth_mode=='keycloak':
            self.run(self.compose('keycloak')+['ps'])
        self.run(app+['ps'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    saved=env_values(ROOT/'.env') if (ROOT/'.env').exists() else {}
    parser.add_argument('--state-dir',type=Path,default=Path(saved.get('CLOUDSAVER_STACK_HOME',str(ROOT/'.env.local-stack'))))
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--no-build',action='store_true',help='Use previously built images')
    parser.add_argument('--bootstrap-secrets',action='store_true',
                        help='Merge generated .env.local-stack secrets into root .env (overwrites your values)')
    parser.add_argument('--auth-mode',choices=('workspace','keycloak','license'),
                        help='Optional override; default is workspace keys via identity-service')
    args=parser.parse_args()
    if args.timeout<30:parser.error('Timeout must be at least 30 seconds')
    for command in ('docker','openssl'):
        if not shutil.which(command):parser.error('Install '+command+' before starting')
    home=args.state_dir.resolve();home.mkdir(parents=True,exist_ok=True,mode=0o700);home.chmod(0o700)
    try:
        stack=Stack(args.env_file.resolve(),home,args.timeout,args.no_build,args.auth_mode,
                    local_creds=not args.bootstrap_secrets)
        stack.run(['docker','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        stack.run(['docker','compose','version'],stdout=subprocess.DEVNULL)
        tenant_id=prepare_settings(args.env_file.resolve(),home)
        sync_secrets(args.env_file.resolve(),home,args.auth_mode,local_creds=not args.bootstrap_secrets)
        stack.start(tenant_id)
    except (subprocess.CalledProcessError,ValueError,OSError) as error:
        print('Startup stopped: '+str(error)+'. Existing volumes and credentials were retained.',file=sys.stderr)
        return 1
    print('All stack health checks passed. Dashboard: http://127.0.0.1:3000')
    print('Platform portal: http://127.0.0.1:3100')
    if stack.auth_mode=='keycloak':
        print('Keycloak: https://keycloak.localhost:8443/admin/')
    elif stack.auth_mode=='workspace':
        print('Sign in to the dashboard with a workspace key from the platform portal (Keys tab).')
    print('Private credentials and configuration: '+str(home))
    if stack.auth_mode=='license':
        print('Offline licence validation is enabled; issue licence tokens from the platform portal when needed.')
    return 0

if __name__=='__main__':raise SystemExit(main())
