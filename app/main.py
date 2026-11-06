"""Runnable CloudSaver enterprise API service v1.8.1."""
import hashlib
import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.store import Store, PostgresStore
from app.schemas import ScanSummary, MultiCloudScanRequest, RemediationRequest
from app.scanner import ScanError

logger = logging.getLogger('cloudsaver')
CHECKOUT_GONE = 'Plan changes are handled by your account manager.'
auth = HTTPBearer(auto_error=False)


def create_app(settings=None, scanner=None, identity_validator=None, delivery_targets=None, delivery_repository=None, job_repository=None, ai_gateway=None, identity_client=None, gitops_config=None, gitops_client=None):
    settings = settings or Settings.load()
    from app.provider_access import ScopedStore
    store = ScopedStore(PostgresStore(settings.database_url) if settings.database_url else Store(settings.database))

    @asynccontextmanager
    async def lifespan(_):
        projector = None
        client = None
        from app.config import directory_mode, key_verifier
        if settings.registry is not None and (
            directory_mode() == 'cutover' or key_verifier() == 'identity'
        ):
            from app.directory_projector import DirectoryProjector
            from app.identity_client import shared_client
            client = identity_client or shared_client()
            projector = DirectoryProjector(settings.registry, client)
            client.directory_listeners.append(projector.nudge)
            try:
                # Replay the change feed on startup; full snapshot resync runs only after a 410.
                projector.run_once()
            except Exception:
                logger.exception('Initial directory projection failed; change feed will retry')
            api.state.projector = projector.start()
        try:
            yield
        finally:
            if projector:
                projector.stop()
            if client is not None and projector is not None:
                client.directory_listeners.remove(projector.nudge)
        from app.cloud_identity import close_providers
        close_providers()
        from database.connection import dispose
        dispose()

    api = FastAPI(title='CloudSaver — Multi-Cloud FinOps', version='1.8.1', lifespan=lifespan)
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
    from app.engineering.api import create_router as engineering_router
    api.include_router(engineering_router(evidence_store,current_tenant))
    from app.governance_api import create_router as governance_workflow_router
    api.include_router(governance_workflow_router(store,evidence_store,current_tenant))
    from app.outcome_api import create_router as outcome_router
    api.include_router(outcome_router(store,evidence_store,current_tenant))
    from app.data_governance_api import create_router as governance_router
    api.include_router(governance_router(evidence_store,current_tenant))
    api.include_router(finops_router(FocusRepository(evidence_store), current_tenant, scan_store=store))
    from app.finops_autopilot_api import create_router as finops_autopilot_router
    api.include_router(finops_autopilot_router(settings, store, evidence_store, current_tenant))
    from app.control_plane_api import create_router as control_plane_router
    api.include_router(control_plane_router(evidence_store,current_tenant))
    from app.observability_api import create_router as observability_router
    api.include_router(observability_router(evidence_store,current_tenant))
    from app.v150_analysis import create_router as connected_analysis_router
    api.include_router(connected_analysis_router(store,current_tenant,FocusRepository(evidence_store)))
    from app.ai_advisory import AIGateway
    ledger = InferenceLedger(evidence_store)
    ai_gateway = ai_gateway or AIGateway(budget=ledger, settings=settings)
    from app.foundry_api import create_router as foundry_router
    from app.foundry import FoundryController
    api.include_router(foundry_router(getattr(ai_gateway, 'foundry', None) or FoundryController(settings, ledger=ledger), current_tenant))
    from app.resource_api import create_router as resource_router
    api.include_router(resource_router(settings, store, current_tenant, ai_gateway, evidence_store))
    from app.jobs_api import create_router as jobs_router
    api.include_router(jobs_router(settings, current_tenant, repository=job_repository))

    from app.delivery_api import create_router as delivery_router
    api.include_router(delivery_router(settings,store,current_tenant,targets=delivery_targets,repository=delivery_repository))
    from app.onboarding_api import onboarding_router, customer_access_router
    api.include_router(onboarding_router())
    api.include_router(customer_access_router(current_tenant))
    from app.settings_api import create_router as settings_router
    api.include_router(settings_router(settings, current_tenant, identity_client=identity_client, scan_store=store))
    from app.kubernetes_api import create_router as kubernetes_router
    api.include_router(kubernetes_router(store, current_tenant, evidence_store=evidence_store))
    from app.assessment_api import create_router as assessment_router
    api.include_router(assessment_router(settings, store, current_tenant, ai_gateway, ledger))
    from app.pillar_analysis_api import create_router as pillar_analysis_router
    api.include_router(pillar_analysis_router(store, current_tenant))
    from app.gitops_api import create_router as gitops_router
    api.include_router(gitops_router(settings, store, current_tenant, config=gitops_config, client=gitops_client))
    from app.drift.event_ingress_api import create_router as drift_ingress_router
    api.include_router(drift_ingress_router(settings, evidence_store))
    from app.drift.drift_ops_api import create_drift_subscriptions_router, create_semantic_router

    api.include_router(create_drift_subscriptions_router(settings, current_tenant))
    api.include_router(create_semantic_router(settings, evidence_store, current_tenant))
    from app.code_mode_api import create_router as code_mode_router
    api.include_router(code_mode_router(evidence_store, current_tenant))

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
        return {'status': 'healthy', 'service': 'cloudsaver', 'version': '1.8.1'}

    @api.get('/api/v1/auth/consent-url')
    def consent_url(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        raise HTTPException(501, 'Interactive consent onboarding is not implemented; ask your platform operator to add cloud accounts in the platform portal')

    @api.get('/api/v1/me')
    def me(tenant=Depends(current_tenant)):
        from app.auth import workspace_response
        return workspace_response(tenant, settings.mode, settings)

    @api.get('/api/v1/analytics')
    def analytics(tenant=Depends(current_tenant)):
        from app.analytics import summarize
        return summarize(store.list(tenant['tenant_id'],1))

    @api.post('/api/v1/billing/webhook')
    def billing_webhook():
        raise HTTPException(410,'Billing webhooks are handled by the platform.')

    @api.get('/api/v1/providers')
    def providers(tenant=Depends(current_tenant)):
        from app.cloud_scope import configured_providers
        return {'providers': configured_providers(tenant),
                'mode': settings.mode, 'execution': 'read_only_synchronous',
                'collection_policy': {'read_retry_attempts':3,'read_budget_seconds':30,
                    'quota_coordination':'redis' if os.getenv('CLOUDSAVER_PROVIDER_REDIS_URL') or os.getenv('REDIS_URL') else 'development_process_only',
                    'billing_retry_state':'queued','provider_freshness_guaranteed':False,
                    'missing_data':'unknown','sandbox_acceptance':'not_established_by_source_presence'},
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
        _abandon_other_running_scans(tenant['tenant_id'], only_stale=True)
        from app.scan_response import scan_for_api
        return [scan_for_api(item) for item in store.list(tenant['tenant_id'], limit)]

    @api.get('/api/v1/scans/{scan_id}', response_model=ScanSummary)
    def scan_detail(scan_id: str, tenant=Depends(current_tenant)):
        result = store.get(tenant['tenant_id'], scan_id)
        if result is None:
            raise HTTPException(404, 'Scan not found')
        if _is_stale_running(result):
            _abandon_other_running_scans(tenant['tenant_id'], only_stale=True)
            result = store.get(tenant['tenant_id'], scan_id) or result
        from app.scan_response import scan_for_api
        return scan_for_api(result)

    @api.post('/api/v1/scans', status_code=201, response_model=ScanSummary)
    def run_scan(tenant=Depends(current_tenant)):
        if not tenant['subscription_ids']:
            raise HTTPException(422, 'No Azure subscriptions are configured; use the multi-cloud scan endpoint')
        return perform_scan(tenant)

    def _async_scans_enabled(store_inner):
        return hasattr(store_inner, 'begin_running_scan') and os.getenv('CLOUDSAVER_ASYNC_SCANS', 'true').lower() != 'false'

    def _prepare_scan(tenant, providers):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        from app.entitlements import enforce_providers, enforce_resource_quota, enforce_subscription_quota, entitlements_for
        plan = entitlements_for(tenant)
        enforce_providers(plan, providers or ['azure'])
        scope_count = (len(tenant.get('subscription_ids', [])) if not providers else sum(
            len(tenant.get(key, [])) for p, key in [('azure', 'subscription_ids'), ('aws', 'aws_accounts'),
            ('gcp', 'gcp_projects'), ('kubernetes', 'kubernetes_clusters')] if p in providers))
        enforce_subscription_quota(plan, scope_count, adding_count=0)
        return plan

    def _running_scan_payload(scan_id, observation_time, tenant, providers):
        return dict(
            scan_id=scan_id,
            timestamp=observation_time,
            status='running',
            mode='multi-cloud' if providers else settings.mode,
            cloud_providers=sorted(providers or ['azure']),
            subscriptions_scanned=len(tenant['subscription_ids']) if not providers or 'azure' in providers else 0,
            total_items_found=0,
            total_monthly_waste_usd=None,
            realizable_monthly_savings_usd=None,
            findings=[],
        )

    def _clear_distributed_scan_lease(tenant_id):
        if os.getenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', '').lower() != 'true':
            return
        from workers.tasks import RedisLease
        lease = RedisLease(os.getenv('REDIS_URL', 'redis://redis:6379/1'))
        try:
            lease.force_clear(tenant_id)
            logger.info('Cleared distributed scan lease workspace=%s', tenant_id)
        except Exception:
            logger.warning('Could not clear distributed scan lease workspace=%s', tenant_id)
        finally:
            lease.close()

    # A worker process can die mid-scan (crash, OOM, redeploy) after status='running' is written but
    # before any completion/failure write runs; nothing else updates that row afterward. Reap it here
    # so a dead scan stops reading as "running" forever instead of only being cleaned up when the next
    # scan starts.
    STALE_RUNNING_MINUTES = 30

    def _is_stale_running(row):
        if row.get('status') != 'running':
            return False
        started = row.get('timestamp')
        if not started:
            return False
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(str(started).replace('Z', '+00:00'))
        except ValueError:
            return False
        return age.total_seconds() > STALE_RUNNING_MINUTES * 60

    def _abandon_other_running_scans(tenant_id, keep_scan_id=None, *, only_stale=False):
        inner = getattr(store, 'inner', store)
        if not hasattr(inner, 'abandon_running_scan'):
            return
        abandoned = False
        for row in store.list_light(tenant_id, 20) if hasattr(store, 'list_light') else store.list(tenant_id, 20):
            if row.get('status') != 'running':
                continue
            scan_id = row.get('scan_id')
            if keep_scan_id and scan_id == keep_scan_id:
                continue
            if only_stale and not _is_stale_running(row):
                continue
            try:
                inner.abandon_running_scan(tenant_id, scan_id)
                abandoned = True
                logger.info('Abandoned stale running scan scan_id=%s', scan_id)
            except Exception:
                logger.warning('Could not abandon stale running scan scan_id=%s', scan_id)
        if abandoned:
            _clear_distributed_scan_lease(tenant_id)

    def _start_scan_async(tenant, providers, response: Response):
        _prepare_scan(tenant, providers)
        tenant_id = tenant['tenant_id']
        lock = locks.setdefault(tenant_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise HTTPException(409, 'A scan is already running for this workspace')
        from app.scan_concurrency import SCAN_LEASE_BUSY, distributed_scan_lease_held
        if distributed_scan_lease_held(tenant_id):
            lock.release()
            raise HTTPException(409, SCAN_LEASE_BUSY)
        scan_id = str(uuid4())
        observation_time = datetime.now(timezone.utc).isoformat()
        _abandon_other_running_scans(tenant_id, keep_scan_id=scan_id)
        preview = _running_scan_payload(scan_id, observation_time, tenant, providers)

        def worker():
            try:
                perform_scan(
                    tenant,
                    providers,
                    scan_id=scan_id,
                    observation_time=observation_time,
                    lock_held=True,
                )
            except HTTPException as exc:
                logger.warning('Background scan failed: %s', exc.detail)
            except Exception:
                logger.exception('Background scan failed')

        threading.Thread(target=worker, name=f'scan-{scan_id[:8]}', daemon=True).start()
        response.status_code = 202
        return preview

    @api.post('/api/v1/scans/multi-cloud', status_code=201, response_model=ScanSummary)
    def run_multi_cloud(payload: MultiCloudScanRequest, response: Response, tenant=Depends(current_tenant)):
        from app.cloud_scope import configured_providers
        from app.provider_access import require_providers
        require_providers(tenant, payload.providers)
        if len(set(payload.providers)) != len(payload.providers) or not set(payload.providers) <= set(configured_providers(tenant)):
            raise HTTPException(422, 'Select unique providers configured for this workspace')
        inner = getattr(store, 'inner', store)
        if _async_scans_enabled(inner):
            return _start_scan_async(tenant, payload.providers, response)
        return perform_scan(tenant, payload.providers)

    def perform_scan(tenant, providers=None, *, scan_id=None, observation_time=None, lock_held=False):
        plan = _prepare_scan(tenant, providers)

        tenant_id = tenant['tenant_id']
        lock = locks.setdefault(tenant_id, threading.Lock())
        if not lock_held and not lock.acquire(blocking=False):
            raise HTTPException(409, 'A scan is already running for this workspace')

        lease, lease_owned, lease_token, heartbeat = None, False, str(uuid4()), None
        provider_label = sorted(providers or ['azure'])
        scan_id = scan_id or str(uuid4())
        observation_time = observation_time or datetime.now(timezone.utc).isoformat()
        if not lock_held:
            _abandon_other_running_scans(tenant_id, keep_scan_id=scan_id)
        progress = None
        scan_completed = False
        inner = getattr(store, 'inner', store)
        if hasattr(inner, 'begin_running_scan'):
            from app.scan_progress import ScanProgress
            progress = ScanProgress(
                inner,
                tenant,
                scan_id,
                observation_time,
                mode='multi-cloud' if providers else settings.mode,
                cloud_providers=sorted(providers or ['azure']),
            )
        logger.info('Scan starting workspace=%s scan_id=%s providers=%s', tenant_id, scan_id, provider_label)
        try:
            if os.getenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', '').lower() == 'true':
                from workers.tasks import RedisLease
                lease = RedisLease(os.getenv('REDIS_URL', 'redis://redis:6379/1'))
                lease_owned = lease.acquire(tenant_id, lease_token)
                if not lease_owned:
                    running = any(
                        row.get('status') == 'running'
                        for row in (store.list_light(tenant_id, 5) if hasattr(store, 'list_light') else store.list(tenant_id, 5))
                    )
                    if not running:
                        lease.force_clear(tenant_id)
                        lease_owned = lease.acquire(tenant_id, lease_token)
                if not lease_owned:
                    raise HTTPException(409, 'A scan is already running for this workspace (distributed lease held)')
                from workers.lease import LeaseHeartbeat
                heartbeat = LeaseHeartbeat(lease, tenant_id, lease_token)
                heartbeat.start()

            from app.scanner import scan_live
            from app.effective_rules import policy_for_tenant
            from app.resource_analysis_service import build_scan_rule_policies
            rule_policy = policy_for_tenant(tenant_id)
            rule_ids = set(rule_policy['enabled_rule_ids']) if rule_policy is not None else None
            if tenant.get('key_id') and rule_policy is None:
                raise ScanError('Analysis policy is unavailable; no scan was saved. Retry when identity-service is available.')
            scan_policies = build_scan_rule_policies(rule_policy, rule_ids)
            inventory = []
            if providers:
                from app.multi_cloud import scan_multi_cloud
                raw_findings, inventory = scan_multi_cloud(tenant, providers, enabled_rule_ids=rule_ids, progress=progress)
            elif scanner:
                scanned = scanner(tenant)
                if isinstance(scanned, tuple):
                    raw_findings, inventory = scanned
                else:
                    raw_findings = scanned
            else:
                raw_findings, inventory = scan_live(
                    tenant,
                    enabled_rule_ids=rule_ids,
                    progress=progress,
                    policies=scan_policies,
                    observed_at=observation_time,
                )

            resource_count = len(inventory) if inventory else len(raw_findings)
            logger.info(
                'Scan collected workspace=%s inventory=%s findings=%s',
                tenant_id,
                len(inventory),
                len(raw_findings),
            )
            from app.entitlements import enforce_resource_quota
            enforce_resource_quota(plan, resource_count)

            from app.cloud_scope import validate_finding_scope
            for finding in raw_findings:
                validate_finding_scope(finding, tenant)

            from app.pricing import attribute_finding_cost
            from app.azure_pricing_evidence import enrich_azure_pricing_evidence, index_inventory
            inventory_index = index_inventory(inventory)
            priced_findings = []
            for finding in raw_findings:
                observation = inventory_index.get(str(finding.get('resource_id', '')).casefold())
                priced_findings.append(enrich_azure_pricing_evidence(finding, observation))
            enriched_findings = [attribute_finding_cost(finding) for finding in priced_findings]

            from app.dependencies import canonical_inventory, group_opportunities
            inventory = canonical_inventory(inventory, observation_time)
            from app.collectors.provenance import compact
            source_ledger = compact(inventory, enriched_findings, observation_time)
            from app.scan_scope_manifest import completed_scopes
            enriched_findings = group_opportunities(enriched_findings, inventory)
            from app.pricing import opportunity_totals
            opportunity = opportunity_totals(enriched_findings)
            total_waste = opportunity['total_monthly_opportunity_usd']
            realizable_savings = opportunity_totals(enriched_findings, realized=True)['total_monthly_opportunity_usd']

            from app.multi_cloud import scope_fingerprint
            from app.analysis_rules import evaluate_inventory, VERSION as rule_version
            from app.inventory import coverage, coverage_manifest
            policies = scan_policies
            if not policies:
                policies = build_scan_rule_policies(rule_policy, rule_ids)
            evaluations = evaluate_inventory(inventory, observed_at=observation_time, policies=policies)
            from app.multicloud_rules import materialize
            enriched_findings=group_opportunities(materialize(enriched_findings,inventory,evaluations),inventory)
            for finding in enriched_findings:validate_finding_scope(finding,tenant)
            opportunity=opportunity_totals(enriched_findings)
            total_waste=opportunity['total_monthly_opportunity_usd']
            realizable_savings=opportunity_totals(enriched_findings,realized=True)['total_monthly_opportunity_usd']
            scope_results = completed_scopes(tenant, providers or ['azure'], source_ledger) if providers or scanner is None else []
            result = dict(
                scan_id=scan_id,
                timestamp=observation_time,
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
                scope_results=scope_results,
                opportunity_summary=opportunity,
                rule_evaluations=evaluations,
                rule_manifest={'version': rule_version, 'enabled_rule_ids': sorted(rule_ids) if rule_ids is not None else None,
                               'workspace_version': (rule_policy or {}).get('version'), 'policies': policies,
                               'policy_source': 'identity' if rule_ids is not None else 'local_catalog'},
                coverage=coverage(inventory, enriched_findings, evaluations),
                coverage_manifest=coverage_manifest(inventory, enriched_findings, evaluations, scope_results=scope_results),
            )
            from app.rule_id_canonical import normalize_scan
            result = normalize_scan(result)
            # Support both Pydantic v1 (parse_obj, dict) and v2 (model_validate, model_dump)
            if hasattr(ScanSummary, 'model_validate'):
                validated = ScanSummary.model_validate(result).model_dump()
            else:
                validated = ScanSummary.parse_obj(result).dict()

            try:
                from app.scan_billing import materialize_scan_billing
                validated = materialize_scan_billing(tenant, validated, FocusRepository(evidence_store))
            except Exception:
                logger.warning('Scan billing materialization failed scan_id=%s', scan_id, exc_info=True)

            previous_scan = None
            try:
                prior = store.list(tenant_id, 1)
                if prior:
                    previous_scan = prior[0]
            except Exception:
                previous_scan = None
            from app.scanner_pipeline import finalize_scan_payload
            finalize_scan_payload(
                validated,
                tenant_id=tenant_id,
                settings=settings,
                previous_completed_scan=previous_scan,
            )

            if heartbeat:
                heartbeat.ensure_owned()
            logger.info('Scan persisting workspace=%s scan_id=%s items=%s', tenant_id, scan_id, result['total_items_found'])
            if progress is not None and hasattr(inner, 'complete_scan'):
                inner.complete_scan(tenant_id, validated, workspace=tenant)
                progress.complete()
            else:
                store.save(tenant_id, validated, workspace=tenant)
            logger.info('Scan saved workspace=%s scan_id=%s', tenant_id, scan_id)
            scan_completed = True
            from app.scan_response import scan_for_api
            return scan_for_api(validated)
        except HTTPException:
            raise
        except ScanError as exc:
            logger.warning('Scan failed (ScanError): %s', str(exc)[:500])
            raise HTTPException(422, str(exc)[:300] or 'The scan could not start.') from None
        except Exception as exc:
            logger.exception('Scan failed (%s)', type(exc).__name__)
            raise HTTPException(502, f'Scan failed. Check cloud credentials, cloud account access and server configuration: {type(exc).__name__}') from None
        finally:
            if progress is not None and not scan_completed:
                progress.abandon()
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



    @api.post('/api/v1/scans/{scan_id}/cancel')
    def cancel_scan(scan_id: str, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        if store.get(tenant['tenant_id'], scan_id) is None:
            raise HTTPException(404, 'Scan not found')
        raise HTTPException(409, 'Completed synchronous scans cannot be cancelled')

    @api.get('/', include_in_schema=False)
    def dashboard():
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><title>CloudSaver Enterprise API</title><h1>CloudSaver Enterprise API v1.8.1</h1><p>The API is running. Start the web-dashboard on port 3000 for the user interface.</p><p><a href="/docs">API reference</a></p></html>')

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


    return api
