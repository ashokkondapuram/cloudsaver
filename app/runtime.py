"""Safe correlation, problem responses, restricted CORS and dependency probes."""
import asyncio
import logging
import os
import re
from contextvars import ContextVar
from http import HTTPStatus
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

request_id = ContextVar('cloudsaver_request_id', default=None)
client_ip = ContextVar('cloudsaver_client_ip', default=None)
CLIENT_IP_HEADER = 'X-CloudSaver-Client-IP'
# Workspace keys (cs_live_/cs_test_), plus legacy 43-character URL-safe and 64-character hex keys.
KEY_PATTERN = re.compile(r'cs_(?:live|test)_[0-9a-z]{12}_[0-9A-Za-z]{43}'
                         r'|(?<![A-Za-z0-9_-])(?:[A-Za-z0-9_-]{43}|[0-9a-fA-F]{64})(?![A-Za-z0-9_-])')
_proxy_cache = {}


def redact(text):
    return re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+','[redacted]',KEY_PATTERN.sub('[redacted]',text)) if isinstance(text,str) else text


def _trusted(peer, entries):
    import ipaddress
    import socket
    import time
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in entries:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
            continue
        except ValueError:
            pass
        cached = _proxy_cache.get(entry)
        if not cached or cached[0] < time.monotonic():
            try:
                resolved = {info[4][0] for info in socket.getaddrinfo(entry, None)}
            except OSError:
                resolved = set()
            cached = (time.monotonic() + 60, resolved)
            _proxy_cache[entry] = cached
        if peer in cached[1]:
            return True
    return False


def resolve_client_ip(request):
    """The socket peer, unless the peer is a configured proxy or internal caller that reports the client."""
    import ipaddress
    peer = request.client.host if request.client else '0.0.0.0'
    candidate = None
    callers = [x.strip() for x in os.getenv('CLOUDSAVER_TRUSTED_CALLERS', '').split(',') if x.strip()]
    proxies = [x.strip() for x in os.getenv('CLOUDSAVER_TRUSTED_PROXIES', '').split(',') if x.strip()]
    if request.headers.get(CLIENT_IP_HEADER) and callers and _trusted(peer, callers):
        candidate = request.headers[CLIENT_IP_HEADER]
    elif request.headers.get('X-Forwarded-For') and proxies and _trusted(peer, proxies):
        candidate = request.headers['X-Forwarded-For'].split(',')[-1].strip()
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else str(ipaddress.ip_address(peer))
    except ValueError:
        return '0.0.0.0'


def problem(request, status, detail, headers=None):
    return JSONResponse({
        'type': 'about:blank', 'title': HTTPStatus(status).phrase,
        'status': status, 'detail': detail, 'instance': request.url.path,
        'request_id': request_id.get(),
    }, status_code=status, media_type='application/problem+json', headers=headers)


def install_log_redaction():
    """Mask anything shaped like a workspace key before a log record is formatted or shipped."""
    factory = logging.getLogRecordFactory()
    if getattr(factory, 'cloudsaver_redacts', False):
        return

    def record(*args, **kwargs):
        item = factory(*args, **kwargs)
        if isinstance(item.msg, str):
            item.msg = redact(item.msg)
        if item.args:
            item.args = tuple(redact(a) if isinstance(a, str) else a for a in item.args) \
                if isinstance(item.args, tuple) else item.args
        return item
    record.cloudsaver_redacts = True
    logging.setLogRecordFactory(record)


def install(app, settings, *, redis_required=False, targets=()):
    install_log_redaction()
    origins = [x.strip() for x in os.getenv('CLOUDSAVER_ALLOWED_ORIGINS', '').split(',') if x.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1'))):
            raise ValueError('CORS origins must be exact HTTPS origins or local HTTP origins')
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                           allow_methods=['GET', 'POST', 'PUT', 'PATCH'], allow_headers=['Authorization', 'Content-Type', 'X-Request-ID','Idempotency-Key','If-Match'],
                           expose_headers=['X-Request-ID', 'Retry-After', 'Location','ETag'])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return problem(request, exc.status_code, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # ValidationError.errors() can contain submitted credentials or plan text.
        return problem(request, 422, 'Invalid or unsupported request')

    @app.middleware('http')
    async def correlation(request, call_next):
        try:
            value = str(UUID(request.headers.get('X-Request-ID', '')))
        except (ValueError, TypeError):
            value = str(uuid4())
        token = request_id.set(value)
        client_ip.set(resolve_client_ip(request))
        try:
            try:
                response = await call_next(request)
            except Exception:
                logging.getLogger('cloudsaver').error('Unhandled request failure request_id=%s', value)
                response = problem(request, 500, 'The service could not complete the request')
            response.headers['X-Request-ID'] = value
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            return response
        finally:
            request_id.reset(token)

    async def database_probe():
        if settings.database_url:
            def ping():
                from database.connection import connect
                with connect(settings.database_url) as db:
                    db.execute("SET LOCAL statement_timeout='2s'")
                    db.execute('SELECT 1')
            await run_in_threadpool(ping)

    async def redis_probe():
        import redis.asyncio as redis
        client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
                                socket_connect_timeout=2, socket_timeout=2)
        try:
            await client.ping()
        finally:
            await client.aclose()

    checks = {}
    if settings.database_url:
        checks['database'] = database_probe
    if redis_required:
        checks['redis'] = redis_probe
    if os.getenv('CLOUDSAVER_AUTH_MODE')=='license':
        async def license_probe():
            from app.offline_license import trust
            await run_in_threadpool(trust)
        checks['offline_license_trust']=license_probe
    for name, url in targets:
        async def check(url=url):
            import httpx
            async with httpx.AsyncClient(timeout=2, follow_redirects=False) as client:
                result = await client.get(url + '/readyz')
                if result.status_code != 200:
                    raise RuntimeError('Dependency unavailable')
        checks[name] = check
    if os.getenv('CLOUDSAVER_ENVIRONMENT')=='production':
        async def directory_probe():
            from app.config import require_directory_freshness
            await run_in_threadpool(require_directory_freshness,settings)
        checks['directory_projection']=directory_probe
    app.state.readiness_checks = checks

    @app.get('/health/live', include_in_schema=False)
    async def liveness():
        return {'status':'alive'}

    @app.get('/health/ready', include_in_schema=False)
    @app.get('/readyz', include_in_schema=False)
    async def readiness():
        async def check(name, probe):
            try:
                await asyncio.wait_for(probe(), timeout=8)
                return name, 'up'
            except Exception:
                return name, 'down'
        result = dict(await asyncio.gather(*(check(name, fn) for name, fn in app.state.readiness_checks.items())))
        ready = all(value == 'up' for value in result.values())
        return JSONResponse({'status': 'ready' if ready else 'unready', 'dependencies': result}, status_code=200 if ready else 503)
