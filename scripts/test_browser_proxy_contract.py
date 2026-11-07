"""Transport acceptance: built Next proxy against a local fake API gateway.

No cloud, identity, database, or real credentials are used. This proves proxy
admission/header transport, not backend authorization or provider acceptance.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--node',default='node');args=parser.parse_args()
    entry=ROOT/'web-dashboard/.next/standalone/server.js'
    if not entry.exists():raise SystemExit('Build web-dashboard first (standalone/server.js is required).')
    calls=[]
    class Gateway(BaseHTTPRequestHandler):
        def handle_request(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            calls.append((self.command,self.path,dict(self.headers),body))
            raw=json.dumps({'transport_fixture':True}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('X-Request-ID','transport-test');self.end_headers();self.wfile.write(raw)
        do_GET=do_POST=do_PUT=do_PATCH=do_DELETE=handle_request
        def log_message(self,*args):pass
    gateway=ThreadingHTTPServer(('127.0.0.1',0),Gateway)
    threading.Thread(target=gateway.serve_forever,daemon=True).start()
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    def request(path,method='GET',body=None):
        headers={'Authorization':'Bearer synthetic-proxy-acceptance','Idempotency-Key':'synthetic-key','If-Match':'"2"','Content-Type':'application/json'}
        try:
            with urlopen(Request(f'http://127.0.0.1:{port}'+path,data=body,method=method,headers=headers),timeout=5) as response:return response.status,response.read()
        except HTTPError as error:return error.code,error.read()
    try:
        with tempfile.TemporaryFile() as log:
            process=subprocess.Popen([args.node,str(entry)],cwd=entry.parent,env={'NODE_ENV':'production','PORT':str(port),'HOSTNAME':'127.0.0.1','NEXT_TELEMETRY_DISABLED':'1','API_GATEWAY_URL':f'http://127.0.0.1:{gateway.server_port}'},stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+30
                while True:
                    if process.poll() is not None:raise AssertionError('Next proxy exited during startup')
                    try:
                        if request('/health/live')[0]==200:break
                    except (URLError,TimeoutError,ConnectionError):pass
                    if time.monotonic()>deadline:raise AssertionError('Next proxy startup timed out')
                    time.sleep(0.1)
                for path in ('/api/v1/analytics','/api/v1/rules/catalog/azure-compute','/api/v1/code-mode/status'):
                    status,raw=request(path);assert status==200,(path,status);assert json.loads(raw)['transport_fixture']
                assert request('/api/v1/settings','PUT',b'{}')[0]==200
                assert calls[-1][0:2]==('PUT','/api/v1/settings')
                headers={k.lower():v for k,v in calls[-1][2].items()}
                assert headers['authorization']=='Bearer synthetic-proxy-acceptance'
                assert headers['idempotency-key']=='synthetic-key' and headers['if-match']=='"2"'
                assert calls[-1][3]==b'{}'
                count=len(calls)
                for path,method in (('/api/v1/rules/catalog/by-pillar','POST'),('/api/v1/kubernetes/grafana/rightsizing/run','GET'),('/api/internal/v1/analysis/resource','GET'),('/api/v1/scans/not-a-uuid/resources','GET'),('/api/v1/semantic/embeddings/backfill-vectors','POST')):
                    assert request(path,method,b'{}' if method=='POST' else None)[0]==404,(path,method)
                assert len(calls)==count,'Rejected requests must never reach the gateway'
                print('Built Next proxy transport acceptance passed (synthetic local gateway; no provider acceptance implied).')
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    finally:gateway.shutdown();gateway.server_close()

if __name__=='__main__':main()
