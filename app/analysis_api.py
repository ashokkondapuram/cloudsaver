"""Internal HTTP API for per-resource analysis (analysis-service)."""
from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix='/internal/v1/analysis')


class AnalyzeResourceBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    resource: dict[str, Any]
    arg_findings: list[dict[str, Any]] = Field(default_factory=list)
    policies: dict[str, Any] = Field(default_factory=dict)
    observed_at: str = Field(min_length=10, max_length=64)


def require_internal_service(authorization: str = Header(default='')):
    expected = os.getenv('CLOUDSAVER_ANALYSIS_INTERNAL_TOKEN') or os.getenv('CLOUDSAVER_IDENTITY_TOKEN') or ''
    if not expected:
        raise HTTPException(503, 'Analysis service internal authentication is not configured')
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Service authentication required')
    token = authorization[7:].strip()
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, 'Invalid service token')


@router.post('/resource')
def analyze_resource_endpoint(body: AnalyzeResourceBody, _auth=Depends(require_internal_service)):
    from app.resource_analysis_service import analyze_resource

    resource = dict(body.resource)
    result = analyze_resource(
        resource,
        arg_findings=body.arg_findings,
        policies=body.policies,
        observed_at=body.observed_at,
    )
    return dict(
        evaluations=result['evaluations'],
        findings=result['findings'],
        recommendations=result['recommendations'],
        assessment=result.get('assessment'),
        resource=resource,
    )


def register(app):
    app.include_router(router)
