"""Aggregate optional platform / tenant-specific pillar rules."""
from __future__ import annotations

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.finding import PillarFinding
from app.analysis_service.platform_rules import run_platform_evaluators


def evaluate(ctx: UnifiedResourceContext) -> list[PillarFinding]:
    return run_platform_evaluators(ctx)
