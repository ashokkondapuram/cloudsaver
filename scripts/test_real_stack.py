"""Run real HTTP through built Next proxy -> gateway -> core, with disposable Redis and synthetic local data.

No cloud account, GitHub publish or model call is enabled. This is a development
transport integration gate, not production identity/IAM/HA acceptance evidence.
"""
import json,os,secrets,socket,subprocess,sys,tempfile,time
from pathlib import Path
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.test_postgres import docker
from app.store import Store
from tests.test_gitops import snapshot,workspace,KEY,TENANT,TARGET


def port():
    with socket.socket() as server:server.bind(('127.0.0.1',0));return server.getsockname()[1]


def main():
    redis='cloudsaver-http-'+secrets.token_hex(6);processes=[];logs=[]
    with tempfile.TemporaryDirectory(prefix='cloudsaver-stack-') as folder:
        try:
            docker('run','-d','--name',redis,'-p','127.0.0.1::6379','redis:7-alpine')
            info=json.loads(docker('inspect',redis))[0];redis_port=info['NetworkSettings']['Ports']['6379/tcp'][0]['HostPort']
            core,gateway,dashboard=port(),port(),port();database=str(Path(folder)/'core.db')
            scan=snapshot();Store(database).save(TENANT,scan,workspace=workspace())
            env=os.environ.copy();env.update(CLOUDSAVER_ENVIRONMENT='development',CLOUDSAVER_AUTH_MODE='workspace',CLOUDSAVER_KEY_VERIFIER='local',CLOUDSAVER_DIRECTORY_MODE='registry',CLOUDSAVER_TENANT_REGISTRY='env',CLOUDSAVER_DATABASE_URL='',CLOUDSAVER_DB=database,CLOUDSAVER_TENANTS=json.dumps([workspace()]),CLOUDSAVER_GITOPS_TARGETS=json.dumps([TARGET]),CLOUDSAVER_GITOPS_PUBLISH='false',CLOUDSAVER_AI_ENABLED='false',CLOUDSAVER_BILLING_CONNECTORS='[]',SCANNER_SERVICE_URL=f'http://127.0.0.1:{core}',API_GATEWAY_URL=f'http://127.0.0.1:{gateway}',REDIS_URL=f'redis://127.0.0.1:{redis_port}/0',NEXT_TELEMETRY_DISABLED='1')
            commands=[([sys.executable,'-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port',str(core),'--no-access-log'],ROOT),([sys.executable,'-m','uvicorn','services.gateway:create_app','--factory','--host','127.0.0.1','--port',str(gateway),'--no-access-log'],ROOT),(['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port',str(dashboard)],ROOT/'web-dashboard')]
            for i,(cmd,cwd) in enumerate(commands):
                log=open(Path(folder)/f'service-{i}.log','w+');logs.append(log)
                processes.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT))
            with httpx.Client(timeout=10,trust_env=False) as client:
                for number,path in ((core,'/healthz'),(gateway,'/healthz'),(dashboard,'/')):
                    deadline=time.monotonic()+60
                    while True:
                        try:
                            r=client.get(f'http://127.0.0.1:{number}'+path)
                            if r.status_code==200:break
                        except httpx.HTTPError:pass
                        if time.monotonic()>deadline or any(p.poll() is not None for p in processes):raise RuntimeError('A test service did not start')
                        time.sleep(.2)
                headers={'Authorization':'Bearer '+KEY,'X-Request-ID':str(uuid4())}
                resource=scan['findings'][0];selection=dict(resource_id=resource['resource_id'],rule_id=resource['rule_id'])
                review=dict(scan_id=scan['scan_id'],target_id='infra',resource_ids=[resource['resource_id']])
                base='/api/v1/scans/'+scan['scan_id']
                # Get the actual deterministic evidence digest before testing the AI gate.
                analysis=client.post(f'http://127.0.0.1:{core}'+base+'/analysis/resource',headers=headers,json=selection)
                assert analysis.status_code==200,analysis.status_code
                ai=dict(selection,evidence_digest=analysis.json()['assessment']['evidence_digest'],target_id='review',idempotency_key=str(uuid4()),acknowledge_external_processing=True)
                cases=[('/api/v1/gitops/preview',review,200),('/api/v1/gitops/requests',dict(review,idempotency_key='real-http-review-'+str(uuid4())),503),('/api/v1/policies/terraform/evaluate',{'plan':{'format_version':'1.2','resource_changes':[],'configuration':{'root_module':{'resources':[]}}}},200),(base+'/analysis/resource',selection,200),(base+'/ai-risk-evaluation',ai,None)]
                for path,payload,expected in cases:
                    direct=client.post(f'http://127.0.0.1:{core}'+path,headers=headers,json=payload)
                    proxied=client.post(f'http://127.0.0.1:{dashboard}'+path,headers=headers,json=payload)
                    assert direct.status_code==proxied.status_code,(path,direct.status_code,proxied.status_code)
                    assert direct.status_code in ({expected} if expected else {403,503}),(path,direct.status_code)
                    if direct.status_code<400:assert direct.json()==proxied.json(),path
                    assert proxied.headers['cache-control']=='no-store'
                assert client.post(f'http://127.0.0.1:{dashboard}/api/v1/gitops/preview',json=review).status_code==401
                html=client.get(f'http://127.0.0.1:{dashboard}/')
                assert html.headers['x-frame-options']=='DENY' and "'nonce-" in html.headers['content-security-policy']
                print('Real HTTP stack: all five gateway workflows, authentication denial and served HTML security headers passed.')
        finally:
            for process in reversed(processes):
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            for log in logs:log.close()
            docker('rm','-f',redis)

if __name__=='__main__':main()
