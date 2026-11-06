"""HTTP client for the analysis-service (per-resource rule evaluation and recommendations)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx


class AnalysisServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _service_url() -> str:
    return (os.getenv('ANALYSIS_SERVICE_URL') or '').rstrip('/')


def _service_token() -> str:
    token = os.getenv('CLOUDSAVER_ANALYSIS_INTERNAL_TOKEN') or os.getenv('CLOUDSAVER_IDENTITY_TOKEN') or ''
    if not token:
        raise AnalysisServiceError('Analysis service token is not configured')
    return token


def analyze_resource(
    resource: dict,
    *,
    arg_findings: list[dict] | None = None,
    policies: dict | None = None,
    observed_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run analysis locally or via analysis-service when ANALYSIS_SERVICE_URL is set."""
    base = _service_url()
    if not base:
        from app.resource_analysis_service import analyze_resource as local_analyze

        return local_analyze(
            resource,
            arg_findings=arg_findings,
            policies=policies,
            observed_at=observed_at,
            now=now,
        )

    now = now or datetime.now(timezone.utc)
    stamp = observed_at or now.isoformat().replace('+00:00', 'Z')
    payload = dict(
        resource=resource,
        arg_findings=list(arg_findings or []),
        policies=policies or {},
        observed_at=stamp,
    )
    try:
        response = httpx.post(
            f'{base}/internal/v1/analysis/resource',
            json=payload,
            headers={'Authorization': f'Bearer {_service_token()}'},
            timeout=httpx.Timeout(120.0, connect=5.0),
        )
    except httpx.HTTPError as error:
        raise AnalysisServiceError('Analysis service unavailable') from error
    if response.status_code >= 400:
        detail = 'Analysis service rejected the request'
        try:
            body = response.json()
            if isinstance(body.get('detail'), str):
                detail = body['detail'][:300]
        except (ValueError, AttributeError):
            pass
        raise AnalysisServiceError(detail, status_code=response.status_code)
    data = response.json()
    if isinstance(data.get('resource'), dict):
        resource.clear()
        resource.update(data['resource'])
    return dict(
        evaluations=list(data.get('evaluations') or []),
        findings=list(data.get('findings') or []),
        recommendations=list(data.get('recommendations') or []),
        assessment=data.get('assessment'),
    )
