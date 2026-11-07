"""Local worker probes based on completed polling progress, not a timer-only heartbeat."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class WorkerHealth:
    def __init__(self, *, max_age=900, clock=time.monotonic, dependency=None, dependency_timeout=0.25):
        self.clock,self.max_age=clock,max_age
        self.progress=clock();self.ready=False;self.stopping=False
        self.server=None
        self.dependency=dependency
        self.dependency_timeout=dependency_timeout
        self.dependency_check=None
        self.dependency_lock=threading.Lock()

    def touch(self,ready=True):
        self.progress=self.clock();self.ready=bool(ready)

    def status(self,path):
        alive=not self.stopping and self.clock()-self.progress<=self.max_age
        if path not in ('/health/live','/health/ready'):return 404,{'status':'not_found'}
        ok=alive and (path=='/health/live' or self.ready)
        if ok and path=='/health/ready' and self.dependency:
            with self.dependency_lock:
                check=self.dependency_check
                if check is None or check['done'].is_set():
                    check={'done':threading.Event(),'ok':False}
                    self.dependency_check=check
                    def probe():
                        try:self.dependency();check['ok']=True
                        except Exception:pass
                        finally:check['done'].set()
                    threading.Thread(target=probe,daemon=True,name='bounded-readiness-dependency').start()
            ok=check['done'].wait(self.dependency_timeout) and check['ok']
        return (200 if ok else 503),{'status':('alive' if path.endswith('/live') else 'ready') if ok else 'unavailable'}

    def start(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                code,payload=owner.status(self.path)
                body=json.dumps(payload).encode()
                self.send_response(code);self.send_header('Content-Type','application/json')
                self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        self.server=HTTPServer((os.getenv('CLOUDSAVER_WORKER_HEALTH_HOST','0.0.0.0'),int(os.getenv('CLOUDSAVER_WORKER_HEALTH_PORT','8099'))),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True,name='worker-health').start()
        return self

    def close(self):
        self.stopping=True
        if self.server:self.server.shutdown();self.server.server_close()
