"""Invoke the Cloudflare Code Mode worker bridge or a test stub."""
import hashlib

from app.code_mode_config import bridge_url, stub_execution
from app.code_mode_validate import validate_snippet


class ExecutionUnavailable(RuntimeError):
    """The executor refused dispatch before any external execution."""


def snippet_digest(snippet: str) -> str:
    return hashlib.sha256(snippet.encode('utf-8')).hexdigest()


def execute_snippet(*, run_id: str, tenant_id: str, snippet: str, input_value: dict) -> dict:
    validate_snippet(snippet)
    url = bridge_url()
    if stub_execution() and not url:
        return {
            'status': 'succeeded',
            'run_id': run_id,
            'tenant_id': tenant_id,
            'output': {'stub': True, 'run_id': run_id, 'tenant_id': tenant_id, 'input_keys': sorted(input_value.keys())},
            'worker_ref': 'stub',
            'snippet_digest': snippet_digest(snippet),
        }
    if not url:
        raise ExecutionUnavailable('Code Mode bridge URL is not configured.')
    raise ExecutionUnavailable('Code Mode remote execution is disabled pending isolated runtime acceptance.')
