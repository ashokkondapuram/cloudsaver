"""Strict request contracts for PROPOSED /api/v1/control-plane routes (not registered)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinancialScenarioRequest(_Strict):
    idempotency_key: str = Field(min_length=8, max_length=128)
    currency: str = Field(min_length=3, max_length=3)
    commitment_fee: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?$")
    uncommitted_baseline: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?$")
    uncommitted_if_absorbed: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?$")
    absorption_proven: bool = False
    new_recurring: str = Field(default="0", pattern=r"^\d+(\.\d+)?$")
    one_time: str = Field(default="0", pattern=r"^\d+(\.\d+)?$")


class ActionAssessmentRequest(_Strict):
    idempotency_key: str = Field(min_length=8, max_length=128)
    action_id: str = Field(min_length=1, max_length=128)
    supported: bool = False
    evidence: dict = Field(default_factory=dict)
