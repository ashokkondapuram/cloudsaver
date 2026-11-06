"""AnalysisService — deterministic 5-pillar evaluation (no provider HTTP)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import EVALUATORS
from app.analysis_service.finding import Pillar, PillarFinding
from app.analysis_service.scoring import score_pillar


class ResourceAnalysisResult(BaseModel):
    canonical_id: str
    provider: str
    resource_type: str
    region: str | None = None
    pillar_scores: dict[str, float]
    findings: list[PillarFinding] = Field(default_factory=list)


class AccountAnalysisResult(BaseModel):
    resources: list[ResourceAnalysisResult] = Field(default_factory=list)
    account_pillar_scores: dict[str, float] = Field(default_factory=dict)
    finding_count: int = 0


class AnalysisService:
    """Evaluates pre-ingested UnifiedResourceContext objects only."""

    def analyze_resource(self, ctx: UnifiedResourceContext) -> ResourceAnalysisResult:
        findings: list[PillarFinding] = []
        with ThreadPoolExecutor(max_workers=len(EVALUATORS), thread_name_prefix='pillar') as pool:
            for batch in pool.map(lambda fn: fn(ctx), EVALUATORS):
                findings.extend(batch)
        scores = {pillar.value: score_pillar(findings, pillar=pillar) for pillar in Pillar}
        return ResourceAnalysisResult(
            canonical_id=ctx.canonical_id,
            provider=ctx.provider,
            resource_type=ctx.resource_type,
            region=ctx.region,
            pillar_scores=scores,
            findings=findings,
        )

    def analyze_account(self, contexts: list[UnifiedResourceContext]) -> AccountAnalysisResult:
        resources = [self.analyze_resource(ctx) for ctx in contexts]
        account_scores: dict[str, list[float]] = {p.value: [] for p in Pillar}
        total_findings = 0
        for item in resources:
            total_findings += len(item.findings)
            for pillar, score in item.pillar_scores.items():
                account_scores[pillar].append(score)
        rolled = {
            pillar: round(sum(values) / len(values), 2) if values else 100.0
            for pillar, values in account_scores.items()
        }
        return AccountAnalysisResult(resources=resources, account_pillar_scores=rolled, finding_count=total_findings)
