"""Run real HTTP through built Next proxy -> gateway -> core, with disposable Redis and synthetic local data.

No cloud account, GitHub publish or model call is enabled. This is a development
transport integration gate, not production identity/IAM/HA acceptance evidence.
"""
import hashlib,hmac,json,os,secrets,socket,subprocess,sys,tempfile,time
from datetime import datetime,timezone
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
            evidence_key=secrets.token_hex(32)
            env=os.environ.copy();env.update(CLOUDSAVER_ENVIRONMENT='development',CLOUDSAVER_AUTH_MODE='workspace',CLOUDSAVER_KEY_VERIFIER='local',CLOUDSAVER_DIRECTORY_MODE='registry',CLOUDSAVER_TENANT_REGISTRY='env',CLOUDSAVER_DATABASE_URL='',CLOUDSAVER_DB=database,CLOUDSAVER_TENANTS=json.dumps([workspace()]),CLOUDSAVER_GITOPS_TARGETS=json.dumps([TARGET]),CLOUDSAVER_GITOPS_PUBLISH='false',CLOUDSAVER_AI_ENABLED='false',CLOUDSAVER_BILLING_CONNECTORS='[]',SCANNER_SERVICE_URL=f'http://127.0.0.1:{core}',API_GATEWAY_URL=f'http://127.0.0.1:{gateway}',REDIS_URL=f'redis://127.0.0.1:{redis_port}/0',NEXT_TELEMETRY_DISABLED='1')
            env['CLOUDSAVER_EVIDENCE_SOURCES']=json.dumps([dict(tenant_id=TENANT,source_id='stack-collector',providers=['azure'],kinds=['audit'],scope_ids=workspace()['subscription_ids'],key_env='CLOUDSAVER_EVIDENCE_KEY_OUTCOMES')])
            env['CLOUDSAVER_GITOPS_AST_INDEX']=json.dumps({scan['findings'][0]['resource_id']:dict(repository=TARGET['repository'],file_path='review.tf',iac_kind='terraform')})
            commands=[([sys.executable,'-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port',str(core),'--no-access-log'],ROOT),([sys.executable,'-m','uvicorn','services.gateway:create_app','--factory','--host','127.0.0.1','--port',str(gateway),'--no-access-log'],ROOT),(['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port',str(dashboard)],ROOT/'web-dashboard')]
            for i,(cmd,cwd) in enumerate(commands):
                log=open(Path(folder)/f'service-{i}.log','w+');logs.append(log)
                processes.append(subprocess.Popen(cmd,cwd=cwd,env={**env,**({'CLOUDSAVER_EVIDENCE_KEY_OUTCOMES':evidence_key} if i==0 else {})},stdout=log,stderr=subprocess.STDOUT))
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
                # Advisory reads must traverse the same BFF/gateway boundary as the console.
                economic=client.get(f'http://127.0.0.1:{dashboard}/api/v1/finops/unit-economics/preview',
                    headers=headers,params=dict(prior_cost='100',current_cost='130',prior_volume='100',current_volume='120'))
                assert economic.status_code==200 and economic.json()['elasticity_ratio']=='1.5'
                mapping=client.get(f'http://127.0.0.1:{dashboard}/api/v1/gitops/resource-mapping',
                    headers=headers,params=dict(resource_id=resource['resource_id']))
                assert mapping.status_code==200 and mapping.json()['repository']==TARGET['repository']
                missing=client.get(f'http://127.0.0.1:{dashboard}/api/v1/gitops/resource-mapping',
                    headers=headers,params=dict(resource_id='not-owned'))
                assert missing.status_code==404
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
                # Exercise persisted outcome writes through the actual BFF and gateway.
                root=f'http://127.0.0.1:{dashboard}/api/v1/outcomes'
                proposal=dict(scan_id=scan['scan_id'],resource_id=resource['resource_id'],request_key=str(uuid4()),action='retirement',proposal='Review retention and provider evidence before retirement.')
                created=client.post(root+'/cases',headers=headers,json=proposal)
                assert created.status_code==201,created.text
                case=created.json()
                retry=client.post(root+'/cases',headers=headers,json=proposal)
                assert retry.status_code==201 and retry.json()['id']==case['id']
                assert client.get(root+'/cases/'+case['id'],headers=headers).json()['state']=='detected'
                receipt=dict(receipt_id=str(uuid4()),source_id='stack-collector',tenant_id=TENANT,case_id=case['id'],provider='azure',scope_id=case['scope_id'],resource_id=case['resource_id'],kind='audit',issued_at=datetime.now(timezone.utc).isoformat(),payload=dict(event_id='synthetic-http-event',operation='delete',status='Succeeded',occurred_at=datetime.now(timezone.utc).isoformat(),before_configuration_digest=case['payload']['configuration_digest']))
                signature=hmac.new(evidence_key.encode(),json.dumps(receipt,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
                signed=client.post(root+'/evidence/receipts',headers={**headers,'X-Evidence-Signature':signature},json=receipt)
                assert signed.status_code==201,signed.text
                assert client.get(root+'/cases/'+case['id'],headers=headers).json()['evidence'][0]['source_id']=='stack-collector'
                assert client.post(root+'/evidence/receipts',headers={**headers,'X-Evidence-Signature':signature},json=dict(receipt,case_id=str(uuid4()))).status_code==422

                for action in ('assign','review'):
                    response=client.post(root+'/cases/'+case['id']+'/actions',headers=headers,json=dict(version=case['version'],action=action,note='Real HTTP synthetic finance review',**({'owner':'team-qa'} if action=='assign' else {})))
                    assert response.status_code==200,response.text
                    case=response.json()
                denied=client.post(root+'/cases/'+case['id']+'/actions',headers=headers,json=dict(version=case['version'],action='approve',change_reference='CHG-HTTP',note='A shared key cannot approve this change'))
                assert denied.status_code==409
                mapping=dict(scan_id=scan['scan_id'],resource_id=resource['resource_id'],version=0,application='payments',team='platform',owner='team-qa',environment='qa',cost_center='cc-qa')
                assert client.put(root+'/ownership',headers=headers,json=mapping).status_code==200
                assert client.get(root+'/ownership',headers=headers).json()['items'][0]['owner']=='team-qa'
                assert client.post(root+'/anomalies/detect',headers=headers,json={}).json()['status']=='missing_billing_evidence'
                assert client.get(root+'/summary',headers=headers).status_code==200
                assert client.get(root+'/cases').status_code==401
                assert client.post(f'http://127.0.0.1:{dashboard}/api/v1/gitops/preview',json=review).status_code==401
                html=client.get(f'http://127.0.0.1:{dashboard}/')
                assert html.headers['x-frame-options']=='DENY' and "'nonce-" in html.headers['content-security-policy']
                print('Real HTTP stack: five legacy gateway workflows, persisted savings/ownership, signed receipt transport/tamper denial, anomaly evidence gaps, human approval denial, authentication denial and served HTML security headers passed.')
        finally:
            for process in reversed(processes):
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            for log in logs:log.close()
            docker('rm','-f',redis)

if __name__=='__main__':main()
