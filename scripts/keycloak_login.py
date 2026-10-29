#!/usr/bin/env python3
"""Local authorization-code/PKCE login; writes a short-lived access token to a private file."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import ssl
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--issuer',required=True)
    parser.add_argument('--ca-bundle')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    from app.keycloak import Binding
    Binding.endpoint(args.issuer)
    output=Path(args.output).resolve()
    if output.exists():parser.error('Output already exists; choose a new private token file')
    verifier=secrets.token_urlsafe(48)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state=secrets.token_urlsafe(32)
    result={}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            query=parse_qs(urlsplit(self.path).query)
            valid=urlsplit(self.path).path=='/callback' and query.get('state')==[state]
            if valid and len(query.get('code',[]))==1:result['code']=query['code'][0]
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type','text/plain');self.send_header('Cache-Control','no-store');self.end_headers()
            self.wfile.write(b'Login received. Return to the terminal.' if valid else b'Invalid login callback.')
    with HTTPServer(('127.0.0.1',8765),Callback) as server:
        server.timeout=1
        query=urlencode(dict(client_id='cloudsaver-console',response_type='code',scope='openid',
                             redirect_uri='http://127.0.0.1:8765/callback',state=state,code_challenge=challenge,code_challenge_method='S256'))
        print('Open this URL in a browser on this same host:\n'+args.issuer+'/protocol/openid-connect/auth?'+query,flush=True)
        deadline=time.monotonic()+180
        while 'code' not in result and time.monotonic()<deadline:server.handle_request()
    if 'code' not in result:raise SystemExit('Login timed out; no credential was saved')
    body=urlencode(dict(grant_type='authorization_code',client_id='cloudsaver-console',code=result['code'],
                        code_verifier=verifier,redirect_uri='http://127.0.0.1:8765/callback')).encode()
    request=Request(args.issuer+'/protocol/openid-connect/token',data=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
    with urlopen(request,context=ssl.create_default_context(cafile=args.ca_bundle),timeout=10) as response:
        raw=response.read(65537)
        if len(raw)>65536:raise SystemExit('Identity response too large')
        token=json.loads(raw)['access_token']
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:handle.write(token+'\n')
    print('Short-lived access token saved to '+str(output)+'. Use it in the dashboard identity-token field.')

if __name__=='__main__':main()
