"""Invoke the Cloudflare Code Mode worker bridge or a test stub."""
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

from app.code_mode_config import bridge_secret, bridge_url, stub_execution
from app.code_mode_validate import validate_snippet


def snippet_digest(snippet: str) -> str:
    return hashlib.sha256(snippet.encode('utf-8')).hexdigest()


def execute_snippet(*, run_id: str, tenant_id: str, snippet: str, input_value: dict) -> dict:
    validate_snippet(snippet)
    url = bridge_url()
    if stub_execution() and not url:
        return {
            'status': 'succeeded',
            'output': {'stub': True, 'run_id': run_id, 'tenant_id': tenant_id, 'input_keys': sorted(input_value.keys())},
            'worker_ref': 'stub',
            'snippet_digest': snippet_digest(snippet),
        }
    if not url:
        raise RuntimeError('Code Mode bridge URL is not configured.')
    secret = bridge_secret()
    if len(secret) < 32:
        raise RuntimeError('Code Mode bridge secret is unavailable.')
    body = json.dumps(
        {'run_id': run_id, 'tenant_id': tenant_id, 'snippet': snippet, 'input': input_value},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        url.rstrip('/') + '/run',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'X-CloudSaver-Code-Mode-Secret': secret,
            'X-CloudSaver-Code-Mode-Signature': signature,
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv('CLOUDFLARE_CODE_MODE_TIMEOUT', '30'))) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', errors='replace')[:500]
        raise RuntimeError(f'Worker bridge returned {error.code}: {detail}') from error
    except urllib.error.URLError as error:
        raise RuntimeError('Worker bridge is unreachable.') from error
    if not isinstance(payload, dict):
        raise RuntimeError('Worker bridge returned an invalid payload.')
    return payload
