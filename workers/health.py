"""Local worker probes based on completed polling progress, not a timer-only heartbeat."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class WorkerHealth:
    def __init__(self, *, max_age=900, clock=time.monotonic, dependency=None):
        self.clock,self.max_age=clock,max_age
        self.progress=clock();self.ready=False;self.stopping=False
        self.server=None
        self.dependency=dependency

    def touch(self,ready=True):
        self.progress=self.clock();self.ready=bool(ready)

    def status(self,path):
        alive=not self.stopping and self.clock()-self.progress<=self.max_age
        if path not in ('/health/live','/health/ready'):return 404,{'status':'not_found'}
        ok=alive and (path=='/health/live' or self.ready)
        if ok and path=='/health/ready' and self.dependency:
            try:self.dependency()
            except Exception:ok=False
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
