from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class WasteFinding(BaseModel):
    rule_id: Literal['ORPHANED_DISK', 'UNASSOCIATED_PUBLIC_IP', 'STOPPED_VM', 'EMPTY_APP_SERVICE_PLAN', 'ORPHANED_DISKS', 'UNASSOCIATED_PUBLIC_IPS', 'STOPPED_VMS', 'ORPHANED_NIC', 'ORPHANED_NSG', 'IDLE_APP_GATEWAY', 'AWS_UNATTACHED_EBS', 'AWS_UNASSOCIATED_EIP', 'AWS_IDLE_RDS', 'GCP_UNATTACHED_DISK', 'GCP_UNASSIGNED_ADDRESS', 'GCP_IDLE_CLOUD_SQL', 'K8S_CPU_OVERSIZED', 'K8S_MEMORY_OVERSIZED', 'K8S_CONTAINER_CPU_OVERREQUEST', 'K8S_CONTAINER_MEMORY_OVERREQUEST', 'K8S_CONTAINER_UNDERPROVISIONED_RISK', 'K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR', 'K8S_NODE_POOL_FRAGMENTATION_WASTE', 'K8S_ABANDONED_WORKLOAD_OR_NAMESPACE', 'K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY', 'K8S_ORPHANED_LOADBALANCER_SERVICE']
    cloud_provider: Literal['azure', 'aws', 'gcp', 'kubernetes'] = 'azure'
    scope_id: str | None = None
    region: str | None = None
    evidence: dict = Field(default_factory=dict)
    severity: Literal['HIGH', 'MEDIUM', 'LOW']
    resource_name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    resource_id: str
    estimated_monthly_waste_usd: float | None = Field(default=None, ge=0)
    details: str
    cost_attribution: Optional[dict] = None

    model_config = ConfigDict(extra='allow', allow_inf_nan=False)


class ScanSummary(BaseModel):
    scan_id: str
    timestamp: str
    status: Literal['completed', 'cancelled', 'failed']
    mode: Literal['azure', 'multi-cloud']
    cloud_providers: list[Literal['azure', 'aws', 'gcp', 'kubernetes']] = Field(default_factory=lambda: ['azure'])
    subscriptions_scanned: int = Field(ge=0)
    total_items_found: int = Field(ge=0)
    total_monthly_waste_usd: float | None = Field(default=None, ge=0)
    realizable_monthly_savings_usd: float | None = Field(default=None, ge=0)
    findings: list[WasteFinding]
    inventory: list[dict] = Field(default_factory=list)

    model_config = ConfigDict(extra='allow', allow_inf_nan=False)


class RemediationRequest(BaseModel):
    resource_ids: list[str] = Field(min_length=1, max_length=50)


class MultiCloudScanRequest(BaseModel):
    providers: list[Literal['azure', 'aws', 'gcp', 'kubernetes']] = Field(min_length=1, max_length=4)
    model_config = ConfigDict(extra='forbid')
