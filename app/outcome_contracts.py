"""Outcome inputs are evidence and review instructions, never cloud execution authority."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
import math
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from app.focus import money


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCreate(Strict):
    scan_id: UUID
    resource_id: str = Field(min_length=1, max_length=2048)
    request_key: UUID
    action: Literal["rightsizing", "retirement"]
    proposal: str = Field(min_length=10, max_length=1000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class CaseAction(Strict):
    version: int = Field(ge=1)
    action: Literal[
        "assign", "review", "approve", "implement", "validate", "reconcile", "reopen"
    ]
    owner: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$"
    )
    note: str = Field(min_length=5, max_length=1000)
    change_reference: str | None = Field(default=None, min_length=3, max_length=200)
    scan_id: UUID | None = None


class Ownership(Strict):
    scan_id: UUID
    resource_id: str = Field(min_length=1, max_length=2048)
    version: int = Field(ge=0)
    application: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    team: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    owner: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    environment: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
    cost_center: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


class Detection(Strict):
    day: date | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class AnomalyAction(Strict):
    version: int = Field(ge=1)
    action: Literal["acknowledge", "assign", "investigate", "note", "resolve"]
    owner: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$"
    )
    note: str = Field(min_length=5, max_length=1000)
    resolution: (
        Literal["actionable", "not_actionable", "planned", "duplicate"] | None
    ) = None


class Suppression(Strict):
    provider: Literal["azure", "aws", "gcp"]
    scope_id: str = Field(min_length=1, max_length=128)
    resource_id: str | None = Field(default=None, max_length=2048)
    start: date
    end: date
    reason: str = Field(min_length=10, max_length=1000)
    change_reference: str = Field(min_length=3, max_length=200)


class Envelope(Strict):
    receipt_id: UUID
    source_id: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
    tenant_id: UUID
    case_id: UUID
    provider: Literal["azure", "aws", "gcp", "kubernetes"]
    scope_id: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=2048)
    kind: Literal["audit", "billing", "slo"]
    issued_at: datetime
    payload: dict


class AuditProof(Strict):
    event_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_:/+=.-]{0,199}$")
    operation: Literal["delete", "resize"]
    status: Literal["Succeeded"]
    occurred_at: datetime
    before_configuration_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    after_configuration_digest: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )


class HealthProof(Strict):
    window_start: datetime
    window_end: datetime
    policy_reference: str = Field(min_length=3, max_length=120)
    health_accepted: StrictBool
    utilization_accepted: StrictBool
    utilization_summary: str = Field(min_length=5, max_length=300)
    configuration_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class BillingProof(Strict):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    baseline_start: date
    baseline_end: date
    post_start: date
    post_end: date
    baseline_recurring_cost: str
    post_recurring_cost: str
    added_recurring_cost: str
    retained_commitment_cost: str
    baseline_billed_cost: str
    post_billed_cost: str
    transition_cost: str
    counterfactual_adjustment: str
    baseline_business_units: str
    post_business_units: str
    business_unit: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,59}$")
    normalization_method: Literal["business_volume_ratio"]
    coverage_complete: StrictBool
    commitments_accounted_for: StrictBool
    credits_accounted_for: StrictBool
    provider_reconciled: StrictBool
    invoice_reference: str | None = Field(default=None, min_length=3, max_length=120)
    ledger_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator(
        "baseline_recurring_cost",
        "post_recurring_cost",
        "added_recurring_cost",
        "retained_commitment_cost",
        "baseline_billed_cost",
        "post_billed_cost",
        "transition_cost",
        "counterfactual_adjustment",
        "baseline_business_units",
        "post_business_units",
        mode="before",
    )
    @classmethod
    def amount(cls, value):
        return money(value)

    @field_validator(
        "baseline_recurring_cost",
        "post_recurring_cost",
        "added_recurring_cost",
        "retained_commitment_cost",
        "transition_cost",
        "baseline_business_units",
        "post_business_units",
    )
    @classmethod
    def nonnegative(cls, value):
        if Decimal(value) < 0:
            raise ValueError("A nonnegative decimal string is required")
        return value


def human(tenant):
    return (
        not tenant.get("key_id")
        and tenant.get("subject_type") != "service_account"
        and bool(
            tenant.get("user_id")
            or tenant.get("subject_type") == "user"
            and tenant.get("subject_id")
        )
    )


def configuration(resource):
    evidence = resource.get("evidence") or {}
    fields = {}
    for key in (
        "size_gb",
        "sku_name",
        "sku_tier",
        "instance_class",
        "allocated_storage_gb",
        "volume_type",
        "storage_type",
        "disk_type",
        "provisioned_iops",
        "throughput_mibps",
        "vm_size",
        "instance_type",
        "machine_type",
        "sku",
        "tier",
        "disk_size_gb",
        "capacity_gb",
        "storage_sku",
        "desired_replicas",
    ):
        value = evidence.get(key)
        if type(value) in (str, int) and len(str(value)) <= 160:
            fields[key] = value
    return fields


def utilization(resource):
    result = {}
    for name, value in (
        (resource.get("evidence") or {}).get("metric_summaries") or {}
    ).items():
        if name not in (
            "cpu_percent",
            "memory_percent",
            "disk_used_percent",
        ) or not isinstance(value, dict):
            continue
        observed = value.get("p95", value.get("observed_value"))
        if type(observed) in (int, float) and math.isfinite(observed):
            result[name] = dict(
                value=observed, sufficient=value.get("sufficient") is True
            )
    return result
