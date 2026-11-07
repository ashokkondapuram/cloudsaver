"""Request models for Grafana Kubernetes rightsizing API."""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RightsizingRunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: UUID
    connector_id: UUID
    cluster: str | None = Field(default=None, max_length=120)
    window_days: int = Field(default=14, ge=1, le=30)


class ConnectorUpdateEnvelope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1)
    connector: dict
