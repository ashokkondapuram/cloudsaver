"""Runnable CloudSaver enterprise API service v1.3.0."""
import hashlib
import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.store import Store, PostgresStore
from app.schemas import ScanSummary, RemediationRequest, MultiCloudScanRequest
from app.scanner import ScanError

logger = logging.getLogger('cloudsaver')
CHECKOUT_GONE = 'Plan changes are handled by your account manager.'
auth = HTTPBearer(auto_error=False)


def create_app(settings=None, scanner=None, identity_validator=None, gitops_config=None, gitops_client=None, delivery_targets=None, delivery_repository=None, job_repository=None, ai_gateway=None):
    settings = settings or Settings.load()
    from app.provider_access import ScopedStore
    store = ScopedStore(PostgresStore(settings.database_url) if settings.database_url else Store(settings.database))

    @asynccontextmanager
    async def lifespan(_):
        yield
        from app.cloud_identity import close_providers
        close_providers()
        from database.connection import dispose
        dispose()

    api = FastAPI(title='CloudSaver — Multi-Cloud FinOps', version='1.3.0', lifespan=lifespan)
    from app.runtime import install
    install(api, settings, redis_required=any(os.getenv(flag, '').lower() == 'true' for flag in (
        'CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', 'CLOUDSAVER_DELIVERY_ENABLED', 'CLOUDSAVER_INTERACTIVE_JOBS')))
    locks = {t['tenant_id']: threading.Lock() for t in settings.tenants}

    from app.auth import tenant_dependency, require_workspace_role, Role
    current_tenant = tenant_dependency(settings, identity_validator)
    from app.enterprise_store import EnterpriseStore
    from app.inference_ledger import InferenceLedger
    from app.focus import FocusRepository
    from app.finops_api import create_router as finops_router
    evidence_store=EnterpriseStore(settings)
    api.include_router(finops_router(FocusRepository(evidence_store),current_tenant))
    from app.assessment_api import create_router as assessment_router
    from app.ai_advisory import AIGateway
    ledger = InferenceLedger(evidence_store)
    ai_gateway = ai_gateway or AIGateway(budget=ledger, settings=settings)
    from app.foundry_api import create_router as foundry_router
    from app.foundry import FoundryController
    api.include_router(foundry_router(getattr(ai_gateway, 'foundry', None) or FoundryController(settings, ledger=ledger), current_tenant))
    api.include_router(assessment_router(settings, store, current_tenant, ai_gateway, ledger))
    from app.resource_api import create_router as resource_router
    api.include_router(resource_router(settings, store, current_tenant, ai_gateway, evidence_store))
    from app.jobs_api import create_router as jobs_router
    api.include_router(jobs_router(settings, current_tenant, repository=job_repository))
    from app.gitops_api import create_router
    api.include_router(create_router(settings,store,current_tenant,config=gitops_config,client=gitops_client))

    from app.delivery_api import create_router as delivery_router
    api.include_router(delivery_router(settings,store,current_tenant,targets=delivery_targets,repository=delivery_repository))
    from app.onboarding_api import onboarding_router, customer_access_router
    api.include_router(onboarding_router())
    api.include_router(customer_access_router(current_tenant))
    from app.service_analysis_api import create_router as service_analysis_router
    api.include_router(service_analysis_router(store, current_tenant))
    from app.kubernetes_api import create_router as kubernetes_router
    api.include_router(kubernetes_router(store, current_tenant))

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
        return {'status': 'healthy', 'service': 'cloudsaver', 'version': '1.3.0'}

    @api.get('/api/v1/auth/consent-url')
    def consent_url(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        raise HTTPException(501, 'Interactive consent onboarding is not implemented; ask your platform operator to add cloud accounts in the platform portal')

    @api.get('/api/v1/me')
    def me(tenant=Depends(current_tenant)):
        from app.auth import workspace_response
        return workspace_response(tenant, settings.mode, settings)

    @api.get('/api/v1/providers')
    def providers(tenant=Depends(current_tenant)):
        from app.cloud_scope import configured_providers
        return {'providers': configured_providers(tenant),
                'mode': settings.mode, 'execution': 'read_only_synchronous',
                'kubernetes_window_days': 14, 'live_cost_support': 'exact Azure meters where available; other providers unknown'}

    @api.get('/api/v1/trends')
    def trends(days: int = 30, scan_id: str | None = None, tenant=Depends(current_tenant)):
        if not 1 <= days <= 365:
            raise HTTPException(422, 'days must be between 1 and 365')
        if scan_id and store.get(tenant['tenant_id'], scan_id) is None:
            raise HTTPException(404, 'Scan not found')
        from app.trends import calculate_trend
        return calculate_trend(store.list(tenant['tenant_id'], 100), days=days, scan_id=scan_id)

    @api.get('/api/v1/billing/entitlements')
    def entitlements(tenant=Depends(current_tenant)):
        from app.entitlements import billing_summary
        workspace = next((t for t in settings.tenants if t['tenant_id'] == tenant['tenant_id']), tenant)
        return billing_summary(tenant, workspace)

    @api.post('/api/v1/billing/checkout')
    def checkout():
        raise HTTPException(410, CHECKOUT_GONE)

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
        if not tenant['subscription_ids']:
            raise HTTPException(422, 'No Azure subscriptions are configured; use the multi-cloud scan endpoint')
        return perform_scan(tenant)

    @api.post('/api/v1/scans/multi-cloud', status_code=201, response_model=ScanSummary)
    def run_multi_cloud(payload: MultiCloudScanRequest, tenant=Depends(current_tenant)):
        from app.cloud_scope import configured_providers
        from app.provider_access import require_providers
        require_providers(tenant, payload.providers)
        if len(set(payload.providers)) != len(payload.providers) or not set(payload.providers) <= set(configured_providers(tenant)):
            raise HTTPException(422, 'Select unique providers configured for this workspace')
        return perform_scan(tenant, payload.providers)

    def perform_scan(tenant, providers=None):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        from app.entitlements import enforce_providers, enforce_resource_quota, enforce_subscription_quota, entitlements_for
        plan = entitlements_for(tenant)
        enforce_providers(plan, providers or ['azure'])
        scope_count = (len(tenant.get('subscription_ids', [])) if not providers else sum(
            len(tenant.get(key, [])) for p, key in [('azure','subscription_ids'),('aws','aws_accounts'),
            ('gcp','gcp_projects'),('kubernetes','kubernetes_clusters')] if p in providers))
        enforce_subscription_quota(plan, scope_count, adding_count=0)

        tenant_id = tenant['tenant_id']
        lock = locks.setdefault(tenant_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise HTTPException(409, 'A scan is already running for this workspace')

        lease, lease_owned, lease_token, heartbeat = None, False, str(uuid4()), None
        try:
            if os.getenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', '').lower() == 'true':
                from workers.tasks import RedisLease
                lease = RedisLease(os.getenv('REDIS_URL', 'redis://redis:6379/1'))
                lease_owned = lease.acquire(tenant_id, lease_token)
                if not lease_owned:
                    raise HTTPException(409, 'A scan is already running for this workspace (distributed lease held)')
                from workers.lease import LeaseHeartbeat
                heartbeat = LeaseHeartbeat(lease, tenant_id, lease_token)
                heartbeat.start()

            from app.scanner import scan_live
            from app.effective_rules import policy_for_tenant
            rule_policy = policy_for_tenant(tenant_id)
            rule_ids = set(rule_policy['enabled_rule_ids']) if rule_policy is not None else None
            if tenant.get('key_id') and rule_policy is None:
                raise ScanError('Analysis policy is unavailable; no scan was saved. Retry when identity-service is available.')
            inventory = []
            if providers:
                from app.multi_cloud import scan_multi_cloud
                raw_findings, inventory = scan_multi_cloud(tenant, providers, enabled_rule_ids=rule_ids)
            elif scanner:
                scanned = scanner(tenant)
                if isinstance(scanned, tuple):
                    raw_findings, inventory = scanned
                else:
                    raw_findings = scanned
            else:
                raw_findings, inventory = scan_live(tenant, enabled_rule_ids=rule_ids)

            resource_count = len(inventory) if inventory else len(raw_findings)
            enforce_resource_quota(plan, resource_count)

            from app.cloud_scope import validate_finding_scope
            for finding in raw_findings:
                validate_finding_scope(finding, tenant)

            from app.pricing import attribute_finding_cost
            enriched_findings = []
            for finding in raw_findings:
                if finding.get('cloud_provider', 'azure') == 'azure':
                    enriched_findings.append(attribute_finding_cost(finding))
                else:
                    enriched_findings.append(finding)

            from app.dependencies import canonical_inventory, group_opportunities
            observation_time = datetime.now(timezone.utc).isoformat()
            inventory = canonical_inventory(inventory, observation_time)
            from app.collectors.provenance import compact
            source_ledger = compact(inventory, enriched_findings, observation_time)
            enriched_findings = group_opportunities(enriched_findings, inventory)
            from app.pricing import opportunity_totals
            opportunity = opportunity_totals(enriched_findings)
            total_waste = opportunity['total_monthly_opportunity_usd']
            realizable_savings = opportunity_totals(enriched_findings, realized=True)['total_monthly_opportunity_usd']

            from app.multi_cloud import scope_fingerprint
            from app.analysis_rules import evaluate_inventory, VERSION as rule_version, RULES
            from app.inventory import coverage, coverage_manifest
            policies = {item['id']: item for item in (rule_policy or {}).get('items', [])}
            if rule_ids is not None:
                from app.kubernetes_rules import DEFINITIONS as KUBERNETES_RULES
                for rid, *_ in (*RULES, *KUBERNETES_RULES):
                    policies.setdefault(rid, {'enabled': rid in rule_ids})
            evaluations = evaluate_inventory(inventory, observed_at=observation_time, policies=policies)
            result = dict(
                scan_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                status='completed',
                mode='multi-cloud' if providers else settings.mode,
                cloud_providers=sorted(providers or ['azure']),
                scope_fingerprint=scope_fingerprint(tenant, providers or ['azure']),
                subscriptions_scanned=len(tenant['subscription_ids']) if not providers or 'azure' in providers else 0,
                total_items_found=len(inventory) if inventory else len(enriched_findings),
                total_monthly_waste_usd=total_waste,
                realizable_monthly_savings_usd=realizable_savings,
                findings=enriched_findings,
                inventory=inventory,
                source_ledger=source_ledger,
                opportunity_summary=opportunity,
                rule_evaluations=evaluations,
                rule_manifest={'version': rule_version, 'enabled_rule_ids': sorted(rule_ids) if rule_ids is not None else None,
                               'workspace_version': (rule_policy or {}).get('version'), 'policies': policies,
                               'policy_source': 'identity' if rule_ids is not None else 'local_catalog'},
                coverage=coverage(inventory, enriched_findings, evaluations),
                coverage_manifest=coverage_manifest(inventory, enriched_findings, evaluations),
            )
            # Support both Pydantic v1 (parse_obj, dict) and v2 (model_validate, model_dump)
            if hasattr(ScanSummary, 'model_validate'):
                validated = ScanSummary.model_validate(result).model_dump()
            else:
                validated = ScanSummary.parse_obj(result).dict()

            if heartbeat:
                heartbeat.ensure_owned()
            store.save(tenant_id, validated, workspace=tenant)
            return validated
        except HTTPException:
            raise
        except ScanError as exc:
            logger.warning('Scan failed (ScanError)')
            raise HTTPException(422, str(exc)[:300] or 'The scan could not start.') from None
        except Exception as exc:
            logger.warning('Scan failed (%s)', type(exc).__name__)
            raise HTTPException(502, f'Scan failed. Check cloud credentials, cloud account access and server configuration: {type(exc).__name__}') from None
        finally:
            if heartbeat:
                heartbeat.stop()
            if lease_owned and lease:
                try:
                    lease.release(tenant_id, lease_token)
                except Exception:
                    pass
            if lease:
                try:
                    lease.close()
                except Exception:
                    pass
            lock.release()

    @api.post('/api/v1/scans/{scan_id}/remediation')
    def remediation(scan_id: str, payload: RemediationRequest, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        from app.remediation import generate_script
        result = store.get(tenant['tenant_id'], scan_id)
        if result is None:
            raise HTTPException(404, 'Scan not found')
        try:
            script = generate_script(result, payload.resource_ids, tenant['tenant_id'], tenant['subscription_ids'])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {'filename': 'cloudsaver-review-remediation.sh', 'script': script}

    @api.post('/api/v1/scans/{scan_id}/remediation-terraform')
    def remediation_terraform(scan_id: str, payload: RemediationRequest, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        from app.entitlements import enforce_terraform_export
        enforce_terraform_export(tenant)
        from app.remediation_terraform import generate_cloud_terraform_hcl
        result = store.get(tenant['tenant_id'], scan_id)
        if result is None:
            raise HTTPException(404, 'Scan not found')
        try:
            hcl_scan = dict(result)
            hcl = generate_cloud_terraform_hcl(hcl_scan, payload.resource_ids, tenant)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {'filename': f'cloudsaver-remediation-{scan_id[:8]}.tf', 'hcl': hcl}

    @api.post('/api/v1/scans/{scan_id}/cancel')
    def cancel_scan(scan_id: str, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        if store.get(tenant['tenant_id'], scan_id) is None:
            raise HTTPException(404, 'Scan not found')
        raise HTTPException(409, 'Completed synchronous scans cannot be cancelled')

    @api.get('/', include_in_schema=False)
    def dashboard():
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><title>CloudSaver Enterprise API</title><h1>CloudSaver Enterprise API v1.3.0</h1><p>The API is running. Start the web-dashboard on port 3000 for the user interface.</p><p><a href="/docs">API reference</a></p></html>')

    return api
