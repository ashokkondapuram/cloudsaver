"""Effective CloudSaver integration settings from platform directory projection or environment."""
from __future__ import annotations

import os


def _platform_block(settings=None):
    registry = getattr(settings, 'registry', None) if settings is not None else None
    if registry is None:
        return {}
    try:
        return registry.platform().get('cloudsaver_integration') or {}
    except Exception:
        return {}


def _env_bool(name: str, default: str = 'false') -> bool:
    return os.getenv(name, default).lower() == 'true'


def _env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw or str(default))
    except ValueError:
        return default


def integration_flag(settings, key: str, env_name: str, *, default='false') -> bool:
    block = _platform_block(settings)
    if key in block and isinstance(block[key], bool):
        return block[key]
    return _env_bool(env_name, default)


def integration_int(settings, key: str, env_name: str, *, default: int = 0) -> int:
    block = _platform_block(settings)
    if key in block and type(block[key]) is int:
        return block[key]
    return _env_int(env_name, default)


def default_billing_currency(settings=None) -> str:
    block = _platform_block(settings)
    code = block.get('default_billing_currency')
    if isinstance(code, str) and len(code) == 3:
        return code.upper()
    env = (os.getenv('CLOUDSAVER_DEFAULT_BILLING_CURRENCY') or 'USD').upper()
    return env if len(env) == 3 else 'USD'
