"""Narrow governance contracts: technical control results never imply organizational compliance."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool

ROLES = (
    "ResourceOwner",
    "SecurityAnalyst",
    "ChangeApprover",
    "BusinessRiskOwner",
    "ComplianceReviewer",
    "Auditor",
    "AutomationIdentity",
)
CONTROL = "AZ-STORAGE-PUBLIC-BLOB-ACCESS"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grant(Strict):
    alias: str = Field(
        default="delegate", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$"
    )
    subject_id: UUID
    role: Literal[
        "ResourceOwner",
        "SecurityAnalyst",
        "ChangeApprover",
        "BusinessRiskOwner",
        "ComplianceReviewer",
        "Auditor",
        "AutomationIdentity",
    ]
    version: int = Field(ge=0)
    active: StrictBool = True
    expires_at: datetime
    maximum_score: int = Field(default=11, ge=1, le=25)
    maximum_exception_days: int = Field(default=7, ge=1, le=30)
    authority_reference: str = Field(min_length=5, max_length=160)


class Mapping(Strict):
    framework: str = Field(min_length=2, max_length=60)
    version: str = Field(min_length=1, max_length=40)
    reference: str = Field(min_length=2, max_length=80)
    rationale: str = Field(min_length=20, max_length=500)


class Policy(Strict):
    version: int = Field(ge=0)
    owner: UUID
    mandatory_obligation: StrictBool = True
    risk_appetite: int = Field(default=6, ge=1, le=25)
    maximum_exception_days: int = Field(default=7, ge=1, le=30)
    rationale: str = Field(min_length=20, max_length=1000)
    mappings: list[Mapping] = Field(default_factory=list, max_length=20)


class Context(Strict):
    application: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    environment: Literal["production", "nonproduction", "unknown"]
    classification: Literal["customer_data", "internal", "public", "unknown"]
    technical_owner: UUID
    business_owner: UUID
    rationale: str = Field(min_length=20, max_length=500)


class Evaluation(Strict):
    scan_id: UUID
    resource_id: str = Field(min_length=1, max_length=2048)
    context: Context


class RiskCreate(Strict):
    request_key: UUID
    finding_ids: list[UUID] = Field(min_length=1, max_length=25)
    business_owner: UUID
    statement: str = Field(min_length=20, max_length=1000)
    treatment_plan: str = Field(min_length=20, max_length=1000)
    inherent_likelihood: int = Field(ge=1, le=5)
    inherent_impact: int = Field(ge=1, le=5)
    residual_likelihood: int = Field(ge=1, le=5)
    residual_impact: int = Field(ge=1, le=5)
    review_date: date


class Plan(Strict):
    change_reference: str = Field(min_length=3, max_length=160)
    steps: list[str] = Field(min_length=1, max_length=10)
    dependency_checks: list[str] = Field(min_length=1, max_length=10)
    validation_steps: list[str] = Field(min_length=1, max_length=10)
    rollback_plan: str = Field(min_length=20, max_length=1000)
    gitops_request_id: UUID | None = None
    agent_task_id: UUID | None = None


class FindingAction(Strict):
    version: int = Field(ge=1)
    action: Literal[
        "triage",
        "propose",
        "approve",
        "implement",
        "verify",
        "close",
        "request_dismissal",
        "dismiss",
        "incident",
        "resume",
        "note",
    ]
    note: str = Field(min_length=10, max_length=1000)
    plan: Plan | None = None
    due_date: date | None = None
    scan_id: UUID | None = None
    receipt_id: UUID | None = None
    incident_reference: str | None = Field(default=None, min_length=3, max_length=160)
    dismissal_kind: Literal["false_positive", "not_applicable"] | None = None


class ExceptionCreate(Strict):
    request_key: UUID
    finding_id: UUID
    justification: str = Field(min_length=20, max_length=1000)
    rejected_alternatives: str = Field(min_length=20, max_length=1000)
    compensating_controls: str = Field(min_length=20, max_length=1000)
    compensation_receipt_id: UUID
    remediation_plan: str = Field(min_length=20, max_length=1000)
    start: datetime
    end: datetime
    review_at: datetime
    review_trigger: str = Field(min_length=10, max_length=300)


class Decision(Strict):
    version: int = Field(ge=1)
    action: Literal["review", "approve", "reject", "revoke", "retire"]
    note: str = Field(min_length=10, max_length=1000)


class Envelope(Strict):
    receipt_id: UUID
    tenant_id: UUID
    finding_id: UUID
    source_id: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
    kind: Literal["implementation", "verification", "compensation", "correction"]
    issued_at: datetime
    payload: dict


class Implementation(Strict):
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    event_id: str = Field(min_length=3, max_length=160)
    operation: Literal["disable_blob_public_access"]
    status: Literal["Succeeded"]
    occurred_at: datetime


class Verification(Strict):
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    scan_id: UUID
    state_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: datetime
    health_accepted: StrictBool
    legitimate_access_accepted: StrictBool
    validation_reference: str = Field(min_length=3, max_length=160)


class Compensation(Strict):
    observed_at: datetime
    valid_until: datetime
    accepted: StrictBool
    evaluation_reference: str = Field(min_length=3, max_length=160)
    controls_summary: str = Field(min_length=20, max_length=500)


class Correction(Strict):
    original_scan_id: UUID
    original_state_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluated_at: datetime
    false_positive_supported: StrictBool
    refutation_reference: str = Field(min_length=3, max_length=160)
