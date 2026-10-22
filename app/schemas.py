from typing import Literal
from pydantic import BaseModel, Field


class WasteFinding(BaseModel):
    rule_id: Literal['ORPHANED_DISK', 'UNASSOCIATED_PUBLIC_IP', 'STOPPED_VM', 'EMPTY_APP_SERVICE_PLAN']
    severity: Literal['HIGH', 'MEDIUM', 'LOW']
    resource_name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    resource_id: str
    estimated_monthly_waste_usd: float | None = Field(default=None, ge=0)
    details: str


class ScanSummary(BaseModel):
    scan_id: str
    timestamp: str
    status: Literal['completed']
    mode: Literal['demo', 'azure']
    subscriptions_scanned: int = Field(ge=1)
    total_items_found: int = Field(ge=0)
    total_monthly_waste_usd: float | None = Field(default=None, ge=0)
    findings: list[WasteFinding]


class RemediationRequest(BaseModel):
    resource_ids: list[str] = Field(min_length=1, max_length=50)
