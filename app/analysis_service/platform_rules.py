"""Platform-extensible pillar evaluators (optional modules registered at process start).

Built-in five-pillar logic lives in ``app.analysis_service.evaluators.*``. This module
lets deployments add **extra** ``PillarFinding`` rows without forking CloudSaver.

**Ways to register**

1. **Optional hooks module** — if importable, ``app.analysis_platform_hooks`` may define::

       def evaluate_platform(ctx: UnifiedResourceContext) -> list[PillarFinding]: ...

2. **Environment** — ``CLOUDSAVER_ANALYSIS_PLATFORM_EVALUATORS`` is a comma-separated list
   of dotted import paths. Each module must define ``evaluate_platform`` with the same
   signature as above.

Evaluators run **after** the built-in cost/performance/reliability/security/operational
functions; all findings participate in pillar scoring.
"""
from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.analysis_service.context import UnifiedResourceContext
    from app.analysis_service.finding import PillarFinding

logger = logging.getLogger('cloudsaver.analysis')

PlatformEvaluator = Callable[['UnifiedResourceContext'], list['PillarFinding']]

_EXTRA: list[PlatformEvaluator] = []
_INITIALIZED = False


def register_platform_evaluator(fn: PlatformEvaluator) -> PlatformEvaluator:
    """Register an evaluator in-process (tests or app wiring)."""
    _EXTRA.append(fn)
    return fn


def reset_platform_evaluators_for_tests() -> None:
    """Clear registry and lazy-import flag (pytest only)."""
    global _INITIALIZED, _EXTRA
    _INITIALIZED = False
    _EXTRA.clear()


def _load_optional_hooks_module() -> None:
    try:
        import app.analysis_platform_hooks as hooks  # type: ignore[import-not-found]
    except ImportError:
        return
    fn = getattr(hooks, 'evaluate_platform', None)
    if callable(fn):
        _EXTRA.append(fn)
    else:
        logger.warning('app.analysis_platform_hooks exists but evaluate_platform is not callable')


def _load_from_environment() -> None:
    raw = os.getenv('CLOUDSAVER_ANALYSIS_PLATFORM_EVALUATORS', '').strip()
    if not raw:
        return
    for dotted in (p.strip() for p in raw.split(',') if p.strip()):
        try:
            module = importlib.import_module(dotted)
        except ImportError:
            logger.exception(
                'CLOUDSAVER_ANALYSIS_PLATFORM_EVALUATORS: failed to import %s',
                dotted,
            )
            continue
        fn = getattr(module, 'evaluate_platform', None)
        if callable(fn):
            _EXTRA.append(fn)
        else:
            logger.warning('Module %s has no callable evaluate_platform', dotted)


def _ensure_platform_evaluators_loaded() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True
    _load_optional_hooks_module()
    _load_from_environment()


def run_platform_evaluators(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    """Run all registered platform evaluators for one resource context."""
    from app.analysis_service.finding import PillarFinding

    _ensure_platform_evaluators_loaded()
    out: list[PillarFinding] = []
    for fn in _EXTRA:
        try:
            batch = fn(ctx)
        except Exception:
            logger.exception('Platform analysis evaluator failed provider=%s resource=%s', ctx.provider, ctx.resource_id)
            continue
        if not batch:
            continue
        if not isinstance(batch, list):
            logger.warning('Platform evaluator %s returned non-list; skipping', getattr(fn, '__name__', fn))
            continue
        out.extend(batch)
    return out
