"""A fake identity-service that replays platform/contracts/fixtures (contract identity-v1)."""
import copy
import json
import secrets
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / 'platform' / 'contracts' / 'fixtures'
TID = '11111111-1111-4111-8111-111111111111'


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text())


class FakeIdentity:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.verify = fixture('verify_valid')
        self.verify_status = 200
        self.changes = fixture('directory_changes')
        self.changes_status = 200
        self.snapshot = fixture('directory_snapshot')
        self.events = fixture('events')
        self.events_status = 200
        self.requests = []
        self.plan_requests = {}
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        self.requests.append(request)
        if request.headers.get('x-service-token') != self.token:
            return httpx.Response(401, json={'detail': 'Unknown caller'})
        path, params = request.url.path, request.url.params
        if request.method == 'POST' and path == '/internal/v1/keys/verify':
            return httpx.Response(self.verify_status, json=copy.deepcopy(self.verify))
        if path == '/internal/v1/directory/changes':
            if self.changes_status != 200:
                return httpx.Response(self.changes_status, json={'detail': 'Resync'})
            after = int(params.get('after', 0))
            return httpx.Response(200, json={'items': [copy.deepcopy(i) for i in self.changes['items'] if i['seq'] > after]})
        if path == '/internal/v1/directory/snapshot':
            return httpx.Response(200, json=copy.deepcopy(self.snapshot))
        if path == '/internal/v1/events':
            if self.events_status == 410:
                return httpx.Response(410, json=fixture('events_gone'))
            if self.events_status != 200:
                return httpx.Response(self.events_status, json={'detail': 'Unavailable'})
            if 'after' not in params:
                return httpx.Response(200, json={'items': [], 'seq': self.events['seq']})
            return httpx.Response(200, json=copy.deepcopy(self.events))
        if request.method == 'POST' and path.startswith('/internal/v1/tenants/') and path.endswith('/plan-change-requests'):
            tenant_id = path.split('/')[4]
            body = json.loads(request.content.decode())
            if tenant_id in self.plan_requests and self.plan_requests[tenant_id].get('status') in ('pending_approval', 'pending_payment'):
                return httpx.Response(409, json={'detail': 'A plan change request is already pending for this workspace.'})
            row = {
                'id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                'tenant_id': tenant_id,
                'customer_id': self.snapshot['workspaces'][0]['customer_id'],
                'current_plan_code': self.snapshot['workspaces'][0]['plan_tier'],
                'requested_plan_code': body['requested_plan_code'],
                'status': 'pending_approval',
                'payment_provider': 'manual',
                'requested_by': body['requested_by'],
                'version': 1,
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
            }
            self.plan_requests[tenant_id] = row
            return httpx.Response(201, json=row)
        if path.startswith('/internal/v1/tenants/') and path.endswith('/plan-change-requests/pending'):
            tenant_id = path.split('/')[4]
            row = self.plan_requests.get(tenant_id)
            return httpx.Response(200, json=copy.deepcopy(row) if row else {})
        return httpx.Response(404, json={'detail': 'Not found'})

    def client(self, cache_seconds=0):
        from app.identity_client import IdentityClient
        return IdentityClient('http://identity', self.token, cache_seconds=cache_seconds, transport=self.transport,
                              subscribe=False)

    def without_plan(self):
        """Simulates a platform that hasn't sent plan blocks yet."""
        self.verify.pop('plan', None)
        for item in self.changes['items']:
            item['snapshot'].pop('plan', None)
        for workspace in self.snapshot['workspaces']:
            workspace.pop('plan', None)
