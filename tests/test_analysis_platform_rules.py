"""Platform-extensible pillar evaluators."""

import sys
import types

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id
from app.analysis_service.platform_rules import register_platform_evaluator, reset_platform_evaluators_for_tests
from app.analysis_service.service import AnalysisService


def test_register_platform_evaluator_runs_in_analysis_service():
    reset_platform_evaluators_for_tests()

    @register_platform_evaluator
    def evaluate_platform(ctx: UnifiedResourceContext):
        return [
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.COST_OPTIMIZATION, rule_id='PLATFORM_UNIT_COST'
                ),
                pillar=Pillar.COST_OPTIMIZATION,
                rule_id='PLATFORM_UNIT_COST',
                severity=Severity.LOW,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                resource_type=ctx.resource_type,
                remediation_action='Unit test platform rule',
            )
        ]

    ctx = UnifiedResourceContext(
        provider='aws',
        resource_id='arn:aws:ec2:us-east-1:1:instance/i-test',
        resource_type='ec2/instance',
    )
    findings = AnalysisService().analyze_resource(ctx).findings
    assert any(f.rule_id == 'PLATFORM_UNIT_COST' for f in findings)
    reset_platform_evaluators_for_tests()


def test_env_lists_extra_evaluator_modules(monkeypatch):
    reset_platform_evaluators_for_tests()
    monkeypatch.delenv('CLOUDSAVER_ANALYSIS_PLATFORM_EVALUATORS', raising=False)

    def evaluate_platform(ctx: UnifiedResourceContext):
        return [
            PillarFinding(
                finding_id=deterministic_finding_id(
                    canonical_id=ctx.canonical_id, pillar=Pillar.OPERATIONAL_EXCELLENCE, rule_id='PLATFORM_ENV_OPS'
                ),
                pillar=Pillar.OPERATIONAL_EXCELLENCE,
                rule_id='PLATFORM_ENV_OPS',
                severity=Severity.MEDIUM,
                canonical_id=ctx.canonical_id,
                provider=ctx.provider,
                resource_type=ctx.resource_type,
                remediation_action='Env-sourced platform rule',
            )
        ]

    mod = types.ModuleType('plat_env_dynamic')
    mod.evaluate_platform = evaluate_platform
    monkeypatch.setitem(sys.modules, 'plat_env_dynamic', mod)
    monkeypatch.setenv('CLOUDSAVER_ANALYSIS_PLATFORM_EVALUATORS', 'plat_env_dynamic')

    ctx = UnifiedResourceContext(
        provider='azure',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm',
        resource_type='microsoft.compute/virtualmachines',
    )
    findings = AnalysisService().analyze_resource(ctx).findings
    assert any(f.rule_id == 'PLATFORM_ENV_OPS' for f in findings)
    reset_platform_evaluators_for_tests()


def test_builtin_evaluator_order_platform_last():
    from app.analysis_service.evaluators import EVALUATORS

    assert EVALUATORS[-1].__module__ == 'app.analysis_service.evaluators.platform'
