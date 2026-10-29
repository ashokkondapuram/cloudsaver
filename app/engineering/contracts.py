"""Bounded declarations are never proof of telemetry, compatibility or authority."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAME = r'^[A-Za-z0-9][A-Za-z0-9 _.:/-]{0,79}$'
KEY = r'^[a-f0-9]{64}$'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class WorkloadCreate(Strict):
    name: str = Field(pattern=NAME)
    environment: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$')
    owner: str = Field(pattern=NAME)
    team: str = Field(pattern=NAME)
    scope_id: UUID
    slo_reference: str | None = Field(default=None, min_length=3, max_length=200)
    peak_reference: str | None = Field(default=None, min_length=3, max_length=200)
    recovery_reference: str | None = Field(default=None, min_length=3, max_length=200)

    @field_validator('slo_reference', 'peak_reference', 'recovery_reference')
    @classmethod
    def reference(cls, value):
        if value is not None and (value != value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError('Use a bounded non-sensitive reference, not a payload')
        return value


class WorkloadUpdate(Strict):
    name: str | None = Field(default=None, pattern=NAME)
    environment: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$')
    owner: str | None = Field(default=None, pattern=NAME)
    team: str | None = Field(default=None, pattern=NAME)
    slo_reference: str | None = Field(default=None, min_length=3, max_length=200)
    peak_reference: str | None = Field(default=None, min_length=3, max_length=200)
    recovery_reference: str | None = Field(default=None, min_length=3, max_length=200)

    @model_validator(mode='after')
    def changes(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set & {'name','environment','owner','team'}):
            raise ValueError('Provide at least one valid change')
        for field in self.model_fields_set - {'name','environment','owner','team'}:
            WorkloadCreate.reference(getattr(self, field))
        return self


class MemberCreate(Strict):
    scan_id: UUID
    resource_key: str = Field(pattern=KEY)


class PlanCreate(Strict):
    member_id: UUID
    scan_id: UUID | None = None
    objective: str = Field(min_length=10, max_length=500, pattern=r'^[^\x00-\x1f]+$')
    action: Literal['azure.vm.rightsize', 'azure.disk.review']
    candidate_sku: str | None = Field(default=None, pattern=r'^[A-Za-z][A-Za-z0-9_.-]{1,79}$')

    @model_validator(mode='after')
    def candidate(self):
        if (self.action == 'azure.vm.rightsize') != (self.candidate_sku is not None):
            raise ValueError('A VM review requires a candidate SKU; a disk review does not accept one')
        return self


class PlanRevision(PlanCreate):
    parent_version: int = Field(ge=1, le=1000)
