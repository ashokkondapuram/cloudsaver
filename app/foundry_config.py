"""Workspace preferences select from tenant-bound, operator-approved inference bindings."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ProviderSettings(Strict):
    enabled: bool = False
    target_id: str | None = Field(None, pattern=r'^[a-z0-9-]{1,40}$')


class AzureSettings(ProviderSettings):
    endpoint_url: str | None = Field(None, max_length=256, pattern=r'^https://[a-z0-9][a-z0-9-]{1,62}\.(?:openai\.azure\.com|services\.ai\.azure\.com|cognitiveservices\.azure\.com)/?$')
    deployment_name: str | None = Field(None, pattern=r'^[A-Za-z0-9._-]{1,160}$')
    api_version: str = Field('2024-10-21', pattern=r'^20[0-9]{2}-[0-9]{2}-[0-9]{2}(?:-preview)?$')
    region: str | None = Field(None, pattern=r'^[a-z0-9-]{2,40}$')
    deployment_sku: Literal['Standard_PAYG', 'Provisioned_PTU'] = 'Standard_PAYG'
    auth_binding: Literal['workspace_managed_identity'] = 'workspace_managed_identity'


class AWSSettings(ProviderSettings):
    region: str | None = Field(None, pattern=r'^[a-z]{2}-[a-z0-9-]{2,24}-[0-9]$')
    model_id: str | None = Field(None, pattern=r'^[A-Za-z0-9._:/-]{1,512}$')
    role_arn: str | None = Field(None, pattern=r'^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}$')
    guardrail_id: str | None = Field(None, pattern=r'^[a-z0-9]{1,64}$')
    guardrail_version: str | None = Field(None, pattern=r'^(?:[1-9][0-9]{0,7}|DRAFT)$')
    external_id: str | None = Field(None, pattern=r'^[0-9a-f-]{36}$')


class GCPSettings(ProviderSettings):
    project_id: str | None = Field(None, pattern=r'^[a-z][a-z0-9-]{4,28}[a-z0-9]$')
    location: str | None = Field(None, pattern=r'^[a-z]+-[a-z]+[0-9]$')
    model_id: str | None = Field(None, pattern=r'^[A-Za-z0-9._-]{1,160}$')
    service_account_email: str | None = Field(None, pattern=r'^[a-z0-9-]{6,30}@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$')
    vpc_sc_enforced: bool = False  # Owner declaration, never proof of a verified service perimeter.


class Providers(Strict):
    azure: AzureSettings = Field(default_factory=AzureSettings)
    aws: AWSSettings = Field(default_factory=AWSSettings)
    gcp: GCPSettings = Field(default_factory=GCPSettings)


class FoundryPolicy(Strict):
    advisory_enabled: bool = False
    allow_anonymized_knowledge_candidates: bool = False
    routing_mode: Literal['same_cloud_only', 'workspace_default_provider'] = 'same_cloud_only'
    primary_provider: Literal['azure', 'aws', 'gcp'] = 'azure'
    max_input_tokens_per_request: int = Field(4000, ge=256, le=16000)
    max_output_tokens_per_request: int = Field(1200, ge=256, le=4096)
    hourly_attempt_budget: int = Field(10, ge=1, le=100)
    monthly_token_limit: int | None = Field(None, ge=512, le=1000000000)


class FoundrySettings(Strict):
    providers: Providers = Field(default_factory=Providers)
    policy: FoundryPolicy = Field(default_factory=FoundryPolicy)


def normalize(value):
    return FoundrySettings.model_validate({} if value is None else value).model_dump()


def provider_fields(target, tenant_id):
    if target.provider == 'azure':
        return dict(endpoint_url=target.endpoint, deployment_name=target.model,
                    api_version=target.api_version or ('2024-05-01-preview' if target.endpoint.endswith('.services.ai.azure.com') else '2024-10-21'),
                    region=target.region, deployment_sku=target.deployment_sku)
    if target.provider == 'aws':
        return dict(region=target.region, model_id=target.model, role_arn=target.role_arn,
                    guardrail_id=target.guardrail_id, guardrail_version=target.guardrail_version, external_id=tenant_id)
    return dict(project_id=target.project, location=target.region, model_id=target.model, service_account_email=target.service_account)


def template(target, tenant_id):
    return dict(provider=target.provider, target_id=target.target_id, model=target.model,
                fields=provider_fields(target, tenant_id), auth=target.auth,
                privacy_attestation='Provider retention and abuse-monitoring settings require independent verification.')
