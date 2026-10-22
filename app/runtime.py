"""Safe correlation, problem responses, restricted CORS and dependency probes."""
import asyncio
import logging
import os
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


def problem(request, status, detail, headers=None):
    return JSONResponse({
        'type': 'about:blank', 'title': HTTPStatus(status).phrase,
        'status': status, 'detail': detail, 'instance': request.url.path,
        'request_id': request_id.get(),
    }, status_code=status, media_type='application/problem+json', headers=headers)


def install(app, settings, *, redis_required=False, targets=()):
    origins = [x.strip() for x in os.getenv('CLOUDSAVER_ALLOWED_ORIGINS', '').split(',') if x.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1'))):
            raise ValueError('CORS origins must be exact HTTPS origins or local HTTP origins')
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                           allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type', 'X-Request-ID'],
                           expose_headers=['X-Request-ID', 'Retry-After', 'Location'])

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
    for name, url in targets:
        async def check(url=url):
            import httpx
            async with httpx.AsyncClient(timeout=2, follow_redirects=False) as client:
                result = await client.get(url + '/readyz')
                if result.status_code != 200:
                    raise RuntimeError('Dependency unavailable')
        checks[name] = check
    app.state.readiness_checks = checks

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
