import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {ManagedIdentityCredential,WorkloadIdentityCredential} from '@azure/identity';
import {createHttpHeaders} from '@azure/core-rest-pipeline';

const tenant='11111111-1111-4111-8111-111111111111',client='22222222-2222-4222-8222-222222222222';

test('patched MSAL remains compatible with noninteractive managed identity token requests',async()=>{
  const saved={IDENTITY_ENDPOINT:process.env.IDENTITY_ENDPOINT,IDENTITY_HEADER:process.env.IDENTITY_HEADER};
  process.env.IDENTITY_ENDPOINT='http://127.0.0.1:4040/token';process.env.IDENTITY_HEADER='synthetic-local-identity-header';let calls=0;
  try{
    const credential=new ManagedIdentityCredential({clientId:client,retryOptions:{maxRetries:0},httpClient:{async sendRequest(request){
      calls++;const url=new URL(request.url);assert.equal(url.origin,'http://127.0.0.1:4040');assert.equal(url.searchParams.get('resource'),'https://management.azure.com');
      assert.equal(request.headers.get('x-identity-header'),'synthetic-local-identity-header');
      return {request,status:200,headers:createHttpHeaders(),bodyAsText:JSON.stringify({access_token:'synthetic-managed-token',token_type:'Bearer',expires_on:String(Math.floor(Date.now()/1000)+3600),resource:'https://management.azure.com',client_id:client})};
    }}});
    const token=await credential.getToken('https://management.azure.com/.default');assert.equal(token?.token,'synthetic-managed-token');assert.ok(calls>0);
  }finally{for(const [key,value] of Object.entries(saved)){if(value===undefined)delete process.env[key];else process.env[key]=value;}}
});

test('patched MSAL remains compatible with federated workload client assertions',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'cloudsaver-identity-'));const file=join(directory,'assertion');await writeFile(file,'synthetic-workload-assertion');let posts=0;
  try{
    const credential=new WorkloadIdentityCredential({tenantId:tenant,clientId:client,tokenFilePath:file,disableInstanceDiscovery:true,retryOptions:{maxRetries:0},httpClient:{async sendRequest(request){
      const url=new URL(request.url);assert.equal(url.origin,'https://login.microsoftonline.com');
      let body;
      if(request.method==='GET')body={authorization_endpoint:`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/authorize`,token_endpoint:`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token`,issuer:`https://login.microsoftonline.com/${tenant}/v2.0`,jwks_uri:`https://login.microsoftonline.com/${tenant}/discovery/v2.0/keys`,end_session_endpoint:`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/logout`};
      else {posts++;assert.equal(new URLSearchParams(String(request.body)).get('client_assertion'),'synthetic-workload-assertion');body={access_token:'synthetic-workload-token',token_type:'Bearer',expires_in:3600,scope:'https://management.azure.com/.default'};}
      return {request,status:200,headers:createHttpHeaders(),bodyAsText:JSON.stringify(body)};
    }}});
    const token=await credential.getToken('https://management.azure.com/.default');assert.equal(token?.token,'synthetic-workload-token');assert.equal(posts,1);
  }finally{await rm(directory,{recursive:true,force:true});}
});
