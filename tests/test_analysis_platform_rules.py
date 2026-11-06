"""Platform-extensible pillar evaluators."""

import sys
import types

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.finding import Pillar, PillarFinding, Severity, deterministic_finding_id
from app.analysis_service.platform_rules import register_platform_evaluator
from app.analysis_service.service import AnalysisService


def test_register_platform_evaluator_runs_in_analysis_service():
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


def test_env_lists_extra_evaluator_modules(monkeypatch):
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


def test_platform_finding_binds_context_fields(monkeypatch):
    """Wrong canonical_id on emitted finding is overwritten from context."""

    @register_platform_evaluator
    def evaluate_platform(ctx: UnifiedResourceContext):
        return [
            {
                'finding_id': 'wrong',
                'pillar': Pillar.SECURITY,
                'rule_id': 'PLATFORM_BIND_TEST',
                'severity': Severity.LOW,
                'canonical_id': 'not-the-real-id',
                'provider': 'wrong',
                'resource_type': 'ignored-type',
                'remediation_action': 'test',
            }
        ]

    ctx = UnifiedResourceContext(
        provider='gcp',
        resource_id='//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm1',
        resource_type='compute.googleapis.com/Instance',
        region='us-central1',
    )
    findings = AnalysisService().analyze_resource(ctx).findings
    f = next(x for x in findings if x.rule_id == 'PLATFORM_BIND_TEST')
    assert f.canonical_id == ctx.canonical_id
    assert f.provider == 'gcp'
    assert f.resource_type == 'compute.googleapis.com/Instance'
    assert f.region == 'us-central1'


def test_platform_dedupes_same_rule_keeps_highest_severity():

    @register_platform_evaluator
    def evaluate_platform(ctx: UnifiedResourceContext):
        base = dict(
            pillar=Pillar.COST_OPTIMIZATION,
            rule_id='PLATFORM_DEDUP',
            canonical_id='x',
            provider='aws',
            resource_type='t',
            remediation_action='x',
        )
        return [
            PillarFinding(
                finding_id='a',
                severity=Severity.LOW,
                **{k: v for k, v in base.items() if k != 'severity'},
            ),
            PillarFinding(
                finding_id='b',
                severity=Severity.HIGH,
                **{k: v for k, v in base.items() if k != 'severity'},
            ),
        ]

    ctx = UnifiedResourceContext(provider='aws', resource_id='arn:aws:s3:::b', resource_type='aws:s3:bucket')
    findings = [f for f in AnalysisService().analyze_resource(ctx).findings if f.rule_id == 'PLATFORM_DEDUP']
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_builtin_evaluator_order_platform_last():
    from app.analysis_service.evaluators import EVALUATORS

    assert EVALUATORS[-1].__module__ == 'app.analysis_service.evaluators.platform'
