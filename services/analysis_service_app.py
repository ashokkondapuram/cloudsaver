"""Standalone Analysis Service HTTP surface (port 8004)."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.loader import contexts_from_scan
from app.analysis_service.service import AccountAnalysisResult, AnalysisService
from services.common import service


class AnalyzeContextsRequest(BaseModel):
    contexts: list[UnifiedResourceContext] = Field(min_length=1)


class AnalyzeScanRequest(BaseModel):
    scan: dict


def create_app(settings=None, identity_validator=None):
    app, settings, tenant = service('analysis-service', settings, identity_validator)

    @app.get('/readyz')
    def readyz():
        return {'status': 'ready', 'service': 'analysis-service'}

    @app.post('/api/v1/analysis/resources', response_model=AccountAnalysisResult)
    def analyze_resources(body: AnalyzeContextsRequest, _tenant=Depends(tenant)):
        return AnalysisService().analyze_account(body.contexts)

    @app.post('/api/v1/analysis/scan', response_model=AccountAnalysisResult)
    def analyze_scan(body: AnalyzeScanRequest, _tenant=Depends(tenant)):
        inventory = body.scan.get('inventory') or []
        if not inventory:
            raise HTTPException(status_code=422, detail='Scan payload must include inventory rows.')
        contexts = contexts_from_scan(body.scan)
        return AnalysisService().analyze_account(contexts)

    return app
