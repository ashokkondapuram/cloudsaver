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

**Safety**

- Each finding is validated with Pydantic; ``finding_id`` is **recomputed** from
  ``canonical_id|pillar|rule_id`` so platform code cannot collide with core ids.
- Fields ``canonical_id``, ``provider``, ``resource_type``, ``region`` are taken from
  the current ``UnifiedResourceContext`` (evaluators cannot stamp another resource).
- Optional cap: ``CLOUDSAVER_ANALYSIS_PLATFORM_MAX_FINDINGS_PER_RESOURCE`` (default 50).
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

_SEVERITY_RANK = None


def _rank(severity):
    global _SEVERITY_RANK
    if _SEVERITY_RANK is None:
        from app.analysis_service.finding import Severity

        _SEVERITY_RANK = {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
        }
    return _SEVERITY_RANK.get(severity, 0)


def _max_platform_findings_per_resource() -> int:
    raw = os.getenv('CLOUDSAVER_ANALYSIS_PLATFORM_MAX_FINDINGS_PER_RESOURCE', '50').strip()
    try:
        n = int(raw)
    except ValueError:
        return 50
    return max(1, min(n, 500))


def _validate_and_bind_finding(ctx: 'UnifiedResourceContext', raw):
    """Return a normalized PillarFinding or None if invalid."""
    from app.analysis_service.finding import PillarFinding, deterministic_finding_id

    if not isinstance(raw, PillarFinding):
        try:
            model = PillarFinding.model_validate(raw)
        except Exception:
            logger.warning('Platform evaluator emitted invalid finding for resource=%s', ctx.resource_id, exc_info=True)
            return None
    else:
        model = raw
    rule_id = (model.rule_id or '').strip()
    if not rule_id or len(rule_id) > 256:
        logger.warning('Platform finding skipped: invalid rule_id for resource=%s', ctx.resource_id)
        return None
    fid = deterministic_finding_id(canonical_id=ctx.canonical_id, pillar=model.pillar, rule_id=rule_id)
    return model.model_copy(
        update=dict(
            finding_id=fid,
            canonical_id=ctx.canonical_id,
            provider=ctx.provider,
            resource_type=ctx.resource_type or model.resource_type,
            region=ctx.region,
        )
    )


def _dedupe_platform_findings(findings: list) -> list:
    """Keep highest-severity row per (pillar, rule_id)."""
    best = {}
    for f in findings:
        key = (f.pillar, f.rule_id)
        if key not in best or _rank(f.severity) > _rank(best[key].severity):
            best[key] = f
    return list(best.values())


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
    from app.analysis_service.builtin_platform_evaluators import evaluate_builtin_platform_rules

    if evaluate_builtin_platform_rules not in _EXTRA:
        _EXTRA.insert(0, evaluate_builtin_platform_rules)
    _load_optional_hooks_module()
    _load_from_environment()


def run_platform_evaluators(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    """Run all registered platform evaluators for one resource context."""
    from app.analysis_service.declarative_rules import evaluate_declarative_rules
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
        for raw in batch:
            bound = _validate_and_bind_finding(ctx, raw)
            if bound is not None:
                out.append(bound)
    try:
        out.extend(evaluate_declarative_rules(ctx))
    except Exception:
        logger.exception('Declarative rules evaluation failed resource=%s', ctx.resource_id)
    out = _dedupe_platform_findings(out)
    cap = _max_platform_findings_per_resource()
    if len(out) > cap:
        logger.warning(
            'Platform findings truncated for resource=%s (%s > cap %s)',
            ctx.resource_id,
            len(out),
            cap,
        )
        out = out[:cap]
    return out
