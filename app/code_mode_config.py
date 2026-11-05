"""Cloudflare Code Mode deployment configuration (operator-controlled)."""
import os


def code_mode_enabled() -> bool:
    return os.getenv('CLOUDSAVER_CODE_MODE_ENABLED', 'false').lower() == 'true'


def bridge_url() -> str:
    return os.getenv('CLOUDFLARE_CODE_MODE_BRIDGE_URL', '').strip()


def bridge_secret() -> str:
    return os.getenv('CLOUDFLARE_CODE_MODE_BRIDGE_SECRET', '')


def stub_execution() -> bool:
    return os.getenv('CLOUDSAVER_CODE_MODE_STUB', 'false').lower() == 'true'


def public_status() -> dict:
    url = bridge_url()
    return {
        'enabled': code_mode_enabled(),
        'bridge_configured': bool(url) or stub_execution(),
        'bridge_host': url.split('://', 1)[-1].split('/', 1)[0] if '://' in url else None,
        'runtime': 'cloudflare-worker-isolate',
        'max_snippet_bytes': 16_384,
        'max_input_bytes': 8_192,
        'requires_human_admin': True,
        'stub_mode': stub_execution() and not url,
    }
