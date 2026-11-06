"""Standardized pillar finding output."""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Pillar(str, Enum):
    COST_OPTIMIZATION = 'COST_OPTIMIZATION'
    PERFORMANCE_EFFICIENCY = 'PERFORMANCE_EFFICIENCY'
    RELIABILITY = 'RELIABILITY'
    SECURITY = 'SECURITY'
    OPERATIONAL_EXCELLENCE = 'OPERATIONAL_EXCELLENCE'


class Severity(str, Enum):
    CRITICAL = 'CRITICAL'
    HIGH = 'HIGH'
    MEDIUM = 'MEDIUM'
    LOW = 'LOW'


class FinancialImpact(BaseModel):
    current_monthly_cost_usd: float | None = None
    projected_monthly_cost_usd: float | None = None
    estimated_monthly_savings_usd: float | None = None


class PillarFinding(BaseModel):
    finding_id: str
    pillar: Pillar
    rule_id: str
    severity: Severity
    canonical_id: str
    provider: str
    region: str | None = None
    resource_type: str
    current_sku: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    financial_impact: FinancialImpact = Field(default_factory=FinancialImpact)
    remediation_action: str


def deterministic_finding_id(*, canonical_id: str, pillar: Pillar | str, rule_id: str) -> str:
    pillar_name = pillar.value if isinstance(pillar, Pillar) else str(pillar)
    digest = hashlib.sha256(f'{canonical_id}|{pillar_name}|{rule_id}'.encode()).hexdigest()
    return digest[:32]
