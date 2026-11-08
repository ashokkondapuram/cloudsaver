"""AnalysisService — deterministic 5-pillar evaluation (no provider HTTP)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import EVALUATORS
from app.analysis_service.finding import Pillar, PillarFinding
from app.analysis_service.scoring import score_pillar


def _has_coverage(ctx: UnifiedResourceContext) -> bool:
    """True when any evidence at all was observed for this resource, so an empty findings list
    can be trusted as "assessed, no issues" rather than "nothing was ever evaluated"."""
    fields = {**ctx.metrics.model_dump(), **ctx.config.model_dump(), **ctx.cost.model_dump()}
    return bool(ctx.activity) or any(value is not None for value in fields.values())


class ResourceAnalysisResult(BaseModel):
    canonical_id: str
    provider: str
    resource_type: str
    region: str | None = None
    pillar_scores: dict[str, float | None]
    findings: list[PillarFinding] = Field(default_factory=list)
    assessment_status: str = 'unassessed'
    score_basis: str = 'finding_severity_only_not_evidence_coverage'


class AccountAnalysisResult(BaseModel):
    resources: list[ResourceAnalysisResult] = Field(default_factory=list)
    account_pillar_scores: dict[str, float] = Field(default_factory=dict)
    finding_count: int = 0
    assessment_status: str = 'unassessed'
    assessed_resource_count: int = 0


class AnalysisService:
    """Evaluates pre-ingested UnifiedResourceContext objects only."""

    def analyze_resource(self, ctx: UnifiedResourceContext) -> ResourceAnalysisResult:
        findings: list[PillarFinding] = []
        with ThreadPoolExecutor(max_workers=len(EVALUATORS), thread_name_prefix='pillar') as pool:
            for batch in pool.map(lambda fn: fn(ctx), EVALUATORS):
                findings.extend(batch)
        assessed = _has_coverage(ctx)
        scores = {pillar.value: score_pillar(findings, pillar=pillar, assessed=assessed) for pillar in Pillar}
        return ResourceAnalysisResult(
            canonical_id=ctx.canonical_id,
            provider=ctx.provider,
            resource_type=ctx.resource_type,
            region=ctx.region,
            pillar_scores=scores,
            findings=findings,
            assessment_status='assessed' if assessed else 'unassessed',
        )

    def analyze_account(self, contexts: list[UnifiedResourceContext]) -> AccountAnalysisResult:
        resources = [self.analyze_resource(ctx) for ctx in contexts]
        account_scores: dict[str, list[float]] = {p.value: [] for p in Pillar}
        total_findings = 0
        assessed_count = 0
        for item in resources:
            total_findings += len(item.findings)
            if item.assessment_status == 'assessed':
                assessed_count += 1
            # Unassessed resources (None scores) are excluded, not averaged in as a healthy 100.
            for pillar, score in item.pillar_scores.items():
                if score is not None:
                    account_scores[pillar].append(score)
        rolled = {
            pillar: round(sum(values) / len(values), 2)
            for pillar, values in account_scores.items() if values
        }
        return AccountAnalysisResult(resources=resources, account_pillar_scores=rolled, finding_count=total_findings,
            assessment_status='assessed' if assessed_count else 'unassessed', assessed_resource_count=assessed_count)
