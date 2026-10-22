from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class WasteFinding(BaseModel):
    rule_id: Literal['ORPHANED_DISK', 'UNASSOCIATED_PUBLIC_IP', 'STOPPED_VM', 'EMPTY_APP_SERVICE_PLAN', 'ORPHANED_DISKS', 'UNASSOCIATED_PUBLIC_IPS', 'STOPPED_VMS']
    severity: Literal['HIGH', 'MEDIUM', 'LOW']
    resource_name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    resource_id: str
    estimated_monthly_waste_usd: float | None = Field(default=None, ge=0)
    details: str
    cost_attribution: Optional[dict] = None

    model_config = ConfigDict(extra='allow')


class ScanSummary(BaseModel):
    scan_id: str
    timestamp: str
    status: Literal['completed', 'cancelled', 'failed']
    mode: Literal['demo', 'azure']
    subscriptions_scanned: int = Field(ge=0)
    total_items_found: int = Field(ge=0)
    total_monthly_waste_usd: float | None = Field(default=None, ge=0)
    realizable_monthly_savings_usd: float | None = Field(default=None, ge=0)
    findings: list[WasteFinding]

    model_config = ConfigDict(extra='allow')


class RemediationRequest(BaseModel):
    resource_ids: list[str] = Field(min_length=1, max_length=50)


class BillingCheckoutRequest(BaseModel):
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    target_tier: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
