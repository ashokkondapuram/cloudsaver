"""Runnable CloudSaver engineering MVP; no external AI integration."""
import hashlib
import hmac
import logging
import threading
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.store import Store, PostgresStore
from app.schemas import ScanSummary, RemediationRequest

logger = logging.getLogger('cloudsaver')
auth = HTTPBearer(auto_error=False)


def create_app(settings=None, scanner=None):
    settings = settings or Settings.load()
    store = PostgresStore(settings.database_url) if settings.database_url else Store(settings.database)
    api = FastAPI(title='CloudSaver — Azure FinOps', version='0.2.0')
    locks = {t['tenant_id']: threading.Lock() for t in settings.tenants}

    def current_tenant(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
        if credentials is None or credentials.scheme.lower() != 'bearer':
            raise HTTPException(401, 'Workspace access key required', headers={'WWW-Authenticate': 'Bearer'})
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        matched = None
        for tenant in settings.tenants:
            if hmac.compare_digest(digest, tenant['api_key_sha256']):
                matched = tenant
        if matched is None:
            raise HTTPException(401, 'Invalid workspace access key', headers={'WWW-Authenticate': 'Bearer'})
        return matched

    @api.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @api.get('/healthz')
    def health():
        return {'status': 'healthy', 'service': 'cloudsaver'}

    @api.get('/api/v1/me')
    def me(tenant=Depends(current_tenant)):
        return {k: tenant[k] for k in ('tenant_id', 'name', 'subscription_ids')} | {'mode': settings.mode}

    @api.get('/api/v1/scans', response_model=list[ScanSummary])
    def history(tenant=Depends(current_tenant), limit: int = 50):
        if not 1 <= limit <= 100:
            raise HTTPException(422, 'limit must be between 1 and 100')
        return store.list(tenant['tenant_id'], limit)

    @api.get('/api/v1/scans/{scan_id}', response_model=ScanSummary)
    def scan_detail(scan_id: str, tenant=Depends(current_tenant)):
        result = store.get(tenant['tenant_id'], scan_id)
        if result is None:
            raise HTTPException(404, 'Scan not found')
        return result

    @api.post('/api/v1/scans', status_code=201, response_model=ScanSummary)
    def run_scan(tenant=Depends(current_tenant)):
        lock = locks[tenant['tenant_id']]
        if not lock.acquire(blocking=False):
            raise HTTPException(409, 'A scan is already running for this workspace')
        try:
            from app.scanner import demo_findings, scan_live
            findings = scanner(tenant) if scanner else (demo_findings() if settings.mode == 'demo' else scan_live(tenant))
            # Demo fixtures are relabeled for the authenticated workspace.
            if settings.mode == 'demo':
                for finding in findings:
                    finding['subscription_id'] = tenant['subscription_ids'][0]
                    finding['resource_id'] = f"/subscriptions/{tenant['subscription_ids'][0]}/resourceGroups/{finding['resource_group']}/providers/{finding['resource_type']}/{finding['resource_name']}"
            result = dict(scan_id=str(uuid4()), timestamp=datetime.now(timezone.utc).isoformat(),
                          status='completed', mode=settings.mode,
                          subscriptions_scanned=len(tenant['subscription_ids']),
                          total_items_found=len(findings),
                          total_monthly_waste_usd=(round(sum(f['estimated_monthly_waste_usd'] or 0 for f in findings), 2) if settings.mode == 'demo' else None),
                          findings=findings)
            result = ScanSummary.model_validate(result).model_dump()
            store.save(tenant['tenant_id'], result, workspace=tenant)
            return result
        except Exception as exc:
            # Never relay SDK exception strings: they can contain cloud identifiers.
            logger.warning('Scan failed (%s)', type(exc).__name__)
            raise HTTPException(502, 'Scan failed. Check cloud credentials, subscription access and server configuration; no partial results were saved.') from None
        finally:
            lock.release()

    @api.post('/api/v1/scans/{scan_id}/remediation')
    def remediation(scan_id: str, payload: RemediationRequest, tenant=Depends(current_tenant)):
        from app.remediation import generate_script
        result = store.get(tenant['tenant_id'], scan_id)
        if result is None:
            raise HTTPException(404, 'Scan not found')
        try:
            script = generate_script(result, payload.resource_ids, tenant['tenant_id'], tenant['subscription_ids'])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {'filename': 'cloudsaver-review-remediation.sh', 'script': script}

    @api.get('/', include_in_schema=False)
    def dashboard():
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><title>CloudSaver API</title><h1>CloudSaver API</h1><p>The API is running. Start the web-dashboard on port 3000 for the application interface.</p><p><a href="/docs">API reference</a></p></html>')

    return api


# Uvicorn factory avoids loading config merely when tests import this module.
# Launch: uvicorn app.main:create_app --factory
