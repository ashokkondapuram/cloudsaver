"""Response contracts for the locally supported engineering review slice."""
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict


class Record(BaseModel):
    model_config=ConfigDict(extra='forbid')


T=TypeVar('T')
class Page(Record,Generic[T]):
    items:list[T]
    next_cursor:str|None


class Requirements(Record):
    slo_reference:str|None=None
    peak_reference:str|None=None
    recovery_reference:str|None=None


class Workload(Record):
    id:str
    tenant_id:str
    name:str
    environment:str
    provider:Literal['azure']
    scope_id:str
    owner:str
    team:str
    requirements:Requirements
    version:int
    created_at:str
    updated_at:str


class Member(Record):
    id:str
    scan_id:str
    resource_key:str
    resource_id:str
    resource_type:str
    resource_name:str
    evidence_digest:str
    created_at:str


class MemberCreated(Record):
    id:str
    workload_id:str
    workload_version:int


class Check(Record):
    code:str
    status:Literal['pass','fail','unknown','not_applicable']
    reason:str
    source:str
    reference:str|None=None
    candidate_sku:str|None=None
    mapping:None=None
    samples:int|None=None
    expected_samples:int|None=None
    coverage_ratio:float|None=None
    p95:float|None=None
    window_start:str|None=None
    window_end:str|None=None
    aggregation_method:str|None=None
    source_resolution_seconds:int|None=None


class FinancialOutcome(Record):
    estimated_opportunity:None=None
    validated_run_rate:None=None
    reconciled_benefit:None=None


class Readiness(Record):
    schema_version:Literal[1]
    rule_id:str
    rule_version:str
    evaluator_digest:str
    decision:Literal['blocked','not_applicable','evidence_required']
    checks:list[Check]
    evidence_digest:str
    policy_digest:str
    evaluated_at:str
    automatic_execution:Literal[False]
    execution_enabled:Literal[False]
    financial_outcome:FinancialOutcome
    next_steps:list[str]


class Parameters(Record):
    schema_version:Literal[1]
    objective:str
    action:Literal['azure.vm.rightsize','azure.disk.review']
    candidate_sku:str|None
    workload_version:int
    member_id:str
    scan_id:str
    resource_key:str
    readiness:Readiness


class Version(Record):
    id:str
    plan_id:str
    version:int
    identity_digest:str
    parameters:Parameters
    state:Literal['evidence_required']
    created_at:str
    workload_id:str
    context_changed:bool
    execution_enabled:Literal[False]


class Plan(Record):
    id:str
    latest:Version


class EventPayload(Record):
    workload:Workload|None=None
    version:int|None=None
    scope_id:str|None=None
    changed_fields:list[str]|None=None
    member_id:str|None=None
    scan_id:str|None=None
    workload_version:int|None=None
    plan_id:str|None=None
    identity_digest:str|None=None


class Event(Record):
    id:str
    kind:str
    actor_hash:str
    payload:EventPayload
    created_at:str


class Policy(Record):
    id:str
    version:int
    minimum_days:int
    minimum_coverage:float
    maximum_gap_minutes:int
    maximum_observation_age_hours:int
    execution_enabled:Literal[False]


class Scope(Record):
    provider:Literal['azure']
    scope_id:str


class Action(Record):
    id:str
    rule_id:str
    rule_version:str
    mode:Literal['review_only']
    sandbox_verified:Literal[False]


class Limits(Record):
    workloads:int
    members_per_workload:int
    plans_per_workload:int
    versions_per_plan:int


class Capabilities(Record):
    schema_version:Literal[1]
    stage:Literal['local_review']
    execution_enabled:Literal[False]
    policy:Policy
    scopes:list[Scope]
    actions:list[Action]
    limits:Limits
    acceptance_required:list[str]
