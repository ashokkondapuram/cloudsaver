"""identity-service: internal verify API, directory change feed and the platform portal admin API."""
import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from identity.auth import ADMIN_CALLERS, DIRECTORY_CALLERS, VERIFY_CALLERS, OperatorAuth, caller_dependency, load_callers
from identity.config import billing_session_flags, env
from identity.domain import IdentityError, Throttled
from identity.keys import key_prefix

logger = logging.getLogger('cloudsaver.identity')
MAX_BODY = 1_048_576


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(max_length=256)
    client_ip: str = Field(max_length=64)
    request_id: str | None = Field(None, max_length=64)


def build_service():
    from identity.events import RedisEvents
    from identity.keys import Peppers
    from identity.service import IdentityService
    from identity.store_postgres import PostgresStore
    from identity.throttle import RedisBackend, Throttle
    from identity.usage import UsageRecorder
    url = env('IDENTITY_DATABASE_URL')
    if not url:
        raise RuntimeError('Set PLATFORM_IDENTITY_DATABASE_URL')
    from identity.knowledge.store import PostgresKnowledgeStore
    knowledge_url = env('KNOWLEDGE_DATABASE_URL')
    knowledge = PostgresKnowledgeStore(knowledge_url, url) if knowledge_url else None
    return IdentityService(PostgresStore(url), Peppers.from_env(), Throttle(RedisBackend()), RedisEvents(),
                           UsageRecorder(), knowledge_store=knowledge)


def problem(request, status, detail, headers=None):
    return JSONResponse({'type': 'about:blank', 'status': status, 'detail': detail, 'instance': request.url.path},
                        status_code=status, media_type='application/problem+json', headers=headers)


def create_app(service=None, callers=None, operator_auth=None, flush_interval=30):
    from identity.redaction import install_log_redaction
    install_log_redaction()
    service = service or build_service()
    callers = callers if callers is not None else load_callers()
    operator_auth = operator_auth or OperatorAuth()

    @asynccontextmanager
    async def lifespan(_):
        from identity.billing.providers import load_provider
        from identity.usage import Flusher

        app.state.billing_provider = load_provider()
        logger.info('Billing provider: %s', app.state.billing_provider)
        flusher = Flusher(service.usage, service.store, flush_interval)
        flusher.start()
        from identity.billing.evaluator import BillingEvaluator
        evaluator = BillingEvaluator(service)
        evaluator.start()
        try:
            yield
        finally:
            evaluator.stop()
            flusher.stop()

    app = FastAPI(title='identity-service', version='1.2.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    verify_caller = caller_dependency(callers, VERIFY_CALLERS)
    directory_caller = caller_dependency(callers, DIRECTORY_CALLERS)
    any_caller = caller_dependency(callers, VERIFY_CALLERS | DIRECTORY_CALLERS | ADMIN_CALLERS)
    portal_caller = caller_dependency(callers, ADMIN_CALLERS)
    operator_dependency = operator_auth.dependency()

    def operator(caller=Depends(portal_caller), identity=Depends(operator_dependency)):
        return identity

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return problem(request, exc.status_code, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo the request: the verify body contains a key.
        return problem(request, 422, 'Invalid or unsupported request')

    @app.exception_handler(IdentityError)
    async def identity_error(request, exc):
        headers = {'Retry-After': str(exc.retry_after)} if isinstance(exc, Throttled) else None
        return problem(request, exc.status, exc.detail, headers)

    @app.middleware('http')
    async def guard(request, call_next):
        if int(request.headers.get('content-length') or 0) > MAX_BODY:
            return problem(request, 413, 'Request body is too large')
        try:
            rid = str(UUID(request.headers.get('X-Request-ID', '')))
        except ValueError:
            rid = str(uuid4())
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:
            logger.error('Unhandled identity request failure request_id=%s', rid)
            response = problem(request, 500, 'The service could not complete the request')
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'X-Frame-Options': 'DENY', 'X-Request-ID': rid})
        return response

    def rid(request):
        return request.state.request_id

    @app.get('/healthz')
    def health():
        return {'status': 'healthy', 'service': 'identity-service'}

    @app.get('/readyz')
    def ready():
        try:
            service.get_platform()
            return {'status': 'ready'}
        except Exception:
            return JSONResponse({'status': 'unready'}, status_code=503)

    # ----- internal ----------------------------------------------------------------------------------
    @app.post('/internal/v1/keys/verify')
    def verify(request: Request, payload: VerifyRequest, caller=Depends(verify_caller)):
        return service.verify(payload.key, payload.client_ip, caller, payload.request_id or rid(request))

    @app.get('/internal/v1/directory/changes')
    def changes(after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500), caller=Depends(directory_caller)):
        return service.changes(after, limit)

    @app.get('/internal/v1/directory/snapshot')
    def directory_snapshot(caller=Depends(directory_caller)):
        return service.directory_snapshot()

    @app.get('/internal/v1/metrics')
    def metrics(caller=Depends(any_caller)):
        return {'verify': [{'result': labels[1], 'caller': labels[2], 'count': count}
                           for labels, count in sorted(service.metrics.items()) if labels[0] == 'verify']}

    @app.get('/internal/v1/events')
    def events(after: int | None = Query(None, ge=0), wait: int = Query(0, ge=0, le=25), caller=Depends(any_caller)):
        return service.poll_events(after, wait)

    @app.post('/internal/v1/access-checks/{check_id}/claim')
    def claim_access_check(check_id: str, caller=Depends(verify_caller)):
        return service.claim_access_check(check_id, caller)

    @app.put('/internal/v1/access-checks/{check_id}/result')
    def complete_access_check(check_id: str, request: Request, payload: dict = Body(...), caller=Depends(verify_caller)):
        return service.complete_access_check(check_id, payload, caller, rid(request))

    @app.post('/internal/v1/tenants/{tenant_id}/plan-change-requests', status_code=201)
    def create_plan_change_request(tenant_id: str, request: Request, payload: dict = Body(...), caller=Depends(verify_caller)):
        return service.create_plan_change_request(tenant_id, payload, caller, rid(request))

    @app.get('/internal/v1/tenants/{tenant_id}/plan-change-requests/pending')
    def pending_plan_change_request(tenant_id: str, caller=Depends(verify_caller)):
        row = service.pending_plan_change_request(tenant_id)
        return row or {}

    @app.get('/internal/v1/tenants/{tenant_id}/analysis-rules/effective')
    def effective_analysis_rules(tenant_id: str, caller=Depends(verify_caller)):
        return service.effective_analysis_rules(tenant_id)

    @app.post('/billing/v1/webhooks/stripe')
    async def stripe_webhook(request: Request, caller=Depends(portal_caller)):
        return service.handle_stripe_webhook(await request.body(), request.headers, rid(request))

    def customer_ip(request: Request):
        forwarded = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        if forwarded:
            return forwarded
        return request.client.host if request.client else '127.0.0.1'

    def customer_grant(request: Request, caller=Depends(verify_caller)):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            raise HTTPException(401, 'Invalid workspace access key.')
        try:
            return service.customer_context_from_key(header[7:].strip(), customer_ip(request), caller)
        except IdentityError as exc:
            raise HTTPException(exc.status, exc.detail) from None

    @app.post('/customer/v1/claim')
    def claim_customer(request: Request, payload: dict = Body(...), caller=Depends(verify_caller)):
        result = service.claim_customer(payload, rid(request))
        if not result.get('valid'):
            raise HTTPException(401, 'Invalid workspace access key.')
        return result

    @app.get('/customer/v1/me')
    def customer_me(grant=Depends(customer_grant)):
        return {k: grant[k] for k in ('customer_id', 'tenant_id', 'subject_id', 'customer_roles', 'roles',
                                      'membership_version')}

    @app.get('/customer/v1/workspaces/{tenant_id}/analysis-rules')
    def customer_rules(tenant_id: str, grant=Depends(customer_grant)):
        return service.customer_analysis_rules(tenant_id, grant)

    @app.put('/customer/v1/workspaces/{tenant_id}/analysis-rules')
    def customer_update_rules(tenant_id: str, request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.customer_analysis_rules(tenant_id, grant, payload, rid(request))

    @app.get('/customer/v1/users')
    def customer_users(grant=Depends(customer_grant)):
        return service.list_customer_users(None, grant)

    @app.post('/customer/v1/users/invite', status_code=201)
    def invite_customer_user(request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.invite_customer_user(None, payload, grant, rid(request))

    @app.post('/customer/v1/users/{user_id}/suspend')
    def suspend_customer_user(user_id: str, request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.set_customer_user_status(None, user_id, payload, 'suspended', grant, rid(request))

    @app.post('/customer/v1/users/{user_id}/reactivate')
    def reactivate_customer_user(user_id: str, request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.set_customer_user_status(None, user_id, payload, 'active', grant, rid(request))

    @app.post('/customer/v1/ownership/transfer')
    def transfer_ownership(request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.transfer_ownership(None, payload, grant, rid(request))

    @app.get('/customer/v1/workspaces/{tenant_id}/members')
    def workspace_members(tenant_id: str, grant=Depends(customer_grant)):
        return service.list_workspace_members(tenant_id, grant)

    @app.put('/customer/v1/workspaces/{tenant_id}/members/{user_id}')
    def update_workspace_member(tenant_id: str, user_id: str, request: Request, payload: dict = Body(...),
                                grant=Depends(customer_grant)):
        return service.update_workspace_member(tenant_id, user_id, payload, grant, rid(request))

    @app.post('/customer/v1/workspaces/{tenant_id}/members/{user_id}/remove')
    def remove_workspace_member(tenant_id: str, user_id: str, request: Request, payload: dict = Body(...),
                                grant=Depends(customer_grant)):
        return service.remove_workspace_member(tenant_id, user_id, payload, grant, rid(request))

    @app.get('/customer/v1/service-accounts')
    def service_accounts(grant=Depends(customer_grant)):
        return service.list_service_accounts(None, grant)

    @app.post('/customer/v1/service-accounts', status_code=201)
    def create_service_account(request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.create_service_account(None, payload, grant, rid(request))

    @app.patch('/customer/v1/service-accounts/{account_id}')
    def update_service_account(account_id: str, request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.update_service_account(account_id, payload, grant, rid(request))

    @app.get('/customer/v1/workspaces/{tenant_id}/keys')
    def customer_keys(tenant_id: str, grant=Depends(customer_grant)):
        return service.list_customer_keys(tenant_id, grant)

    @app.post('/customer/v1/workspaces/{tenant_id}/keys', status_code=201)
    def customer_issue_key(tenant_id: str, request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.issue_customer_workspace_key(tenant_id, payload, grant, rid(request))

    @app.post('/customer/v1/keys/{key_id}/revoke')
    def customer_revoke_key(key_id: str, request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.revoke_customer_key(key_id, payload, grant, rid(request))

    @app.post('/customer/v1/keys/{key_id}/rotate', status_code=201)
    def customer_rotate_key(key_id: str, request: Request, payload: dict = Body(...), grant=Depends(customer_grant)):
        return service.rotate_customer_key(key_id, payload, grant, rid(request))

    @app.get('/customer/v1/audit')
    def customer_audit(before: str | None = None, limit: int = Query(50, ge=1, le=200),
                       action: str | None = Query(None, max_length=40), grant=Depends(customer_grant)):
        return service.customer_audit(grant, before, limit, action)

    @app.get('/customer/v1/access-export')
    def customer_access_export(grant=Depends(customer_grant)):
        from fastapi.responses import Response
        return Response(service.export_customer_access(grant), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="access-review.csv"'})

    # ----- portal admin API --------------------------------------------------------------------------
    @app.get('/admin/v1/session')
    def session(identity=Depends(operator)):
        return {'actor': identity['actor'], 'display_name': identity['display_name'], 'roles': identity['roles'],
                'auth_mode': identity['auth_mode'], 'provider_scoped_keys': service.provider_scoped_keys,
                'environment': service.environment, 'key_prefix': key_prefix(service.environment),
                **billing_session_flags()}

    @app.get('/admin/v1/customers')
    def customers(q: str | None = Query(None, max_length=120), status: str | None = None, cursor: str | None = None,
                  limit: int = Query(50, ge=1, le=200), identity=Depends(operator)):
        return service.list_customers(q, status, cursor, limit)

    @app.post('/admin/v1/customers', status_code=201)
    def create_customer(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_customer(payload, identity, rid(request))

    @app.get('/admin/v1/customers/{customer_id}')
    def customer(customer_id: str, identity=Depends(operator)):
        return service.get_customer(customer_id)

    @app.post('/admin/v1/customers/{customer_id}/bootstrap-key', status_code=201)
    def bootstrap_key(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.issue_bootstrap_key(customer_id, payload, identity, rid(request))

    @app.patch('/admin/v1/customers/{customer_id}')
    def update_customer(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_customer(customer_id, payload, identity, rid(request))

    @app.delete('/admin/v1/customers/{customer_id}')
    def delete_customer(customer_id: str, request: Request, version: int = Query(..., ge=0), identity=Depends(operator)):
        return service.set_customer_status(customer_id, {'version': version}, 'deleted', identity, rid(request))

    @app.post('/admin/v1/customers/{customer_id}/suspend')
    def suspend_customer(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_customer_status(customer_id, payload, 'suspended', identity, rid(request))

    @app.post('/admin/v1/customers/{customer_id}/reactivate')
    def reactivate_customer(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_customer_status(customer_id, payload, 'active', identity, rid(request))

    @app.get('/admin/v1/workspaces')
    def workspaces(q: str | None = Query(None, max_length=120), status: str | None = None, customer_id: str | None = None,
                   cursor: str | None = None, limit: int = Query(50, ge=1, le=200), identity=Depends(operator)):
        return service.list_workspaces(q, status, customer_id, cursor, limit)

    @app.post('/admin/v1/workspaces', status_code=201)
    def create_workspace(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_workspace(payload, identity, rid(request))

    @app.get('/admin/v1/workspaces/{tenant_id}')
    def workspace(tenant_id: str, identity=Depends(operator)):
        return service.get_workspace(tenant_id)

    @app.patch('/admin/v1/workspaces/{tenant_id}')
    def update_workspace(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_workspace(tenant_id, payload, identity, rid(request))

    @app.put('/admin/v1/workspaces/{tenant_id}/scopes/{provider}')
    def replace_scopes(tenant_id: str, provider: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.replace_scopes(tenant_id, provider, payload, identity, rid(request))

    @app.post('/admin/v1/workspaces/{tenant_id}/suspend')
    def suspend_workspace(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_workspace_status(tenant_id, payload, 'suspended', identity, rid(request))

    @app.post('/admin/v1/workspaces/{tenant_id}/reactivate')
    def reactivate_workspace(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_workspace_status(tenant_id, payload, 'active', identity, rid(request))

    @app.delete('/admin/v1/workspaces/{tenant_id}')
    def delete_workspace(tenant_id: str, request: Request, version: int = Query(..., ge=0), identity=Depends(operator)):
        return service.set_workspace_status(tenant_id, {'version': version}, 'deleted', identity, rid(request))

    @app.get('/admin/v1/platform-settings')
    def platform(identity=Depends(operator)):
        return service.get_platform()

    @app.put('/admin/v1/platform-settings')
    def update_platform(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_platform(payload, identity, rid(request))

    @app.post('/admin/v1/access-checks', status_code=202)
    def create_access_check(request: Request, payload: dict = Body(default={}), identity=Depends(operator)):
        return service.create_access_check(payload, identity, rid(request))

    @app.get('/admin/v1/access-checks/{check_id}')
    def access_check(check_id: str, identity=Depends(operator)):
        return service.get_access_check(check_id)

    @app.get('/admin/v1/workspaces/{tenant_id}/keys')
    def keys(tenant_id: str, identity=Depends(operator)):
        return service.list_keys(tenant_id)

    @app.post('/admin/v1/workspaces/{tenant_id}/keys', status_code=201)
    def issue_key(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.issue_key(tenant_id, payload, identity, rid(request))

    @app.post('/admin/v1/workspaces/{tenant_id}/keys/revoke-all')
    def revoke_all(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.revoke_all(tenant_id, payload, identity, rid(request))

    @app.get('/admin/v1/workspaces/{tenant_id}/usage')
    def workspace_usage(tenant_id: str, start: str | None = Query(None, alias='from'), end: str | None = Query(None, alias='to'),
                        identity=Depends(operator)):
        return service.workspace_usage(tenant_id, start, end)

    @app.get('/admin/v1/keys/{key_id}')
    def key(key_id: str, identity=Depends(operator)):
        return service.get_key(key_id)

    @app.patch('/admin/v1/keys/{key_id}')
    def update_key(key_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_key(key_id, payload, identity, rid(request))

    @app.post('/admin/v1/keys/{key_id}/rotate', status_code=201)
    def rotate_key(key_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.rotate_key(key_id, payload, identity, rid(request))

    @app.post('/admin/v1/keys/{key_id}/revoke')
    def revoke_key(key_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.revoke_key(key_id, payload, identity, rid(request))

    @app.get('/admin/v1/keys/{key_id}/usage')
    def key_usage(key_id: str, start: str | None = Query(None, alias='from'), end: str | None = Query(None, alias='to'),
                  identity=Depends(operator)):
        return service.key_usage(key_id, start, end)

    @app.get('/admin/v1/audit')
    def audit(customer_id: str | None = None, tenant_id: str | None = None, key_id: str | None = Query(None, max_length=12),
              actor: str | None = Query(None, max_length=120), action: str | None = Query(None, max_length=40),
              before: str | None = None, limit: int = Query(50, ge=1, le=200), identity=Depends(operator)):
        return service.audit({'customer_id': customer_id, 'tenant_id': tenant_id, 'key_id': key_id, 'actor': actor,
                              'action': action}, before, limit)

    @app.get('/admin/v1/failures')
    def failures(tenant_id: str | None = None, source_ip: str | None = Query(None, max_length=64),
                 reason: str | None = Query(None, max_length=24), start: str | None = Query(None, alias='from'),
                 identity=Depends(operator)):
        return service.failures({'tenant_id': tenant_id, 'source_ip': source_ip, 'reason': reason}, start)

    @app.get('/admin/v1/plans')
    def plans(identity=Depends(operator)):
        return service.list_plans()

    @app.get('/admin/v1/plans/{code}')
    def plan(code: str, identity=Depends(operator)):
        return service.get_plan(code)

    @app.post('/admin/v1/plans', status_code=201)
    def create_plan(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_plan(payload, identity, rid(request))

    @app.patch('/admin/v1/plans/{code}')
    def update_plan(code: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_plan(code, payload, identity, rid(request))

    @app.post('/admin/v1/plans/{code}/retire')
    def retire_plan(code: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.retire_plan(code, payload, identity, rid(request))

    @app.get('/admin/v1/analysis/rules')
    def analysis_rules(identity=Depends(operator)):
        return service.list_analysis_rules()

    @app.get('/admin/v1/workspaces/{tenant_id}/analysis-rules')
    def workspace_analysis_rules(tenant_id: str, identity=Depends(operator)):
        return service.list_workspace_analysis_rules(tenant_id)

    @app.put('/admin/v1/workspaces/{tenant_id}/analysis-rules')
    def update_workspace_analysis_rules(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_workspace_analysis_rules(tenant_id, payload, identity, rid(request))

    @app.get('/internal/v1/knowledge/retrieve')
    def retrieve_knowledge(provider: str, service_category: str, rule_ids: str = Query('', max_length=2400), caller=Depends(verify_caller)):
        return service.retrieve_knowledge(provider, service_category, rule_ids.split(',') if rule_ids else [])

    @app.get('/internal/v1/ai-policy')
    def effective_ai_policy(caller=Depends(verify_caller)):
        return service.get_ai_policy()

    @app.get('/admin/v1/ai-policy')
    def read_ai_policy(identity=Depends(operator)):
        return service.get_ai_policy()

    @app.put('/admin/v1/ai-policy')
    def update_ai_policy(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_ai_policy(payload, identity, rid(request))

    @app.get('/admin/v1/knowledge/metrics')
    def knowledge_metrics(identity=Depends(operator)):
        return service.knowledge_metrics()

    @app.post('/admin/v1/knowledge/publications/{publication_id}/review')
    def review_publication(publication_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.review_knowledge_publication(publication_id, payload, identity, rid(request))

    @app.get('/admin/v1/knowledge/publications')
    def knowledge_publications(status: str | None = Query(None, max_length=16), limit: int = Query(50, ge=1, le=200),
                               cursor: str | None = Query(None, max_length=20), identity=Depends(operator)):
        return service.list_knowledge_publications(status, limit, cursor)

    @app.post('/admin/v1/knowledge/publications', status_code=201)
    def create_knowledge_publication(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_knowledge_publication(payload, identity, rid(request))

    @app.patch('/admin/v1/knowledge/publications/{publication_id}')
    def update_knowledge_publication(publication_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_knowledge_publication(publication_id, payload, identity, rid(request))

    @app.get('/admin/v1/billing/settings')
    def billing_settings(identity=Depends(operator)):
        return service.get_billing_settings()

    @app.put('/admin/v1/billing/settings')
    def update_billing_settings(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_billing_settings(payload, identity, rid(request))

    @app.get('/admin/v1/billing/customers')
    def billing_customers(billing_state: str | None = Query(None, max_length=16), plan: str | None = Query(None, max_length=16),
                          renews_before: str | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=200),
                          identity=Depends(operator)):
        return service.list_billing_customers(billing_state, plan, renews_before, cursor, limit)

    @app.get('/admin/v1/customers/{customer_id}/subscriptions')
    def customer_subscriptions(customer_id: str, identity=Depends(operator)):
        return service.list_customer_subscriptions(customer_id)

    @app.post('/admin/v1/customers/{customer_id}/subscriptions', status_code=201)
    def create_customer_subscription(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_customer_subscription(customer_id, payload, identity, rid(request))

    @app.get('/admin/v1/customers/{customer_id}/payments')
    def customer_payments(customer_id: str, identity=Depends(operator)):
        return service.list_customer_payments(customer_id)

    @app.post('/admin/v1/customers/{customer_id}/payments', status_code=201)
    def create_customer_payment(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_customer_payment(customer_id, payload, identity, rid(request))

    @app.get('/admin/v1/customers/{customer_id}/entitlements')
    def customer_entitlements(customer_id: str, identity=Depends(operator)):
        return service.get_customer_entitlements(customer_id)

    @app.get('/admin/v1/subscriptions/{subscription_id}')
    def get_subscription(subscription_id: str, identity=Depends(operator)):
        return service.get_subscription(subscription_id)

    @app.patch('/admin/v1/subscriptions/{subscription_id}')
    def update_subscription(subscription_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_subscription(subscription_id, payload, identity, rid(request))

    @app.post('/admin/v1/subscriptions/{subscription_id}/cancel')
    def cancel_subscription(subscription_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.cancel_subscription(subscription_id, payload, identity, rid(request))

    @app.get('/admin/v1/plan-change-requests')
    def plan_change_requests(status: str | None = Query(None, max_length=24), limit: int = Query(50, ge=1, le=200),
                             identity=Depends(operator)):
        return service.list_plan_change_requests(status or 'pending_approval', limit)

    @app.post('/admin/v1/plan-change-requests/{request_id}/approve')
    def approve_plan_change_request(request_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.approve_plan_change_request(request_id, payload, identity, rid(request))

    @app.post('/admin/v1/plan-change-requests/{request_id}/reject')
    def reject_plan_change_request(request_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.reject_plan_change_request(request_id, payload, identity, rid(request))

    return app
