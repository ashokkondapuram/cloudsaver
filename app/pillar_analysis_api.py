"""Read persisted scan pillar_analysis on scan and resource APIs."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.domain.resource.identity import canonical_resource_id


def pillar_analysis_block(scan: dict) -> dict | None:
    block = scan.get('pillar_analysis')
    return block if isinstance(block, dict) else None


def pillar_analysis_row_for_resource(scan: dict, provider: str, resource_id: str) -> dict | None:
    block = pillar_analysis_block(scan)
    if not block:
        return None
    target = canonical_resource_id(provider, resource_id)
    for row in block.get('resources') or []:
        if isinstance(row, dict) and row.get('provider') == provider and row.get('canonical_id') == target:
            return row
    return None


def pillar_scores_for_resource(scan: dict, provider: str, resource_id: str) -> dict[str, float] | None:
    row = pillar_analysis_row_for_resource(scan, provider, resource_id)
    if not row:
        return None
    scores = row.get('pillar_scores')
    return scores if isinstance(scores, dict) else None


def create_router(store, current_tenant):
    router = APIRouter(prefix='/api/v1')

    @router.get('/scans/{scan_id}/pillar-analysis')
    def scan_pillar_analysis(scan_id: UUID, tenant=Depends(current_tenant)):
        scan = store.get(tenant['tenant_id'], str(scan_id))
        if scan is None:
            raise HTTPException(404, 'Scan not found')
        block = pillar_analysis_block(scan)
        if block is None:
            raise HTTPException(404, 'Pillar analysis is not available for this scan')
        return block

    return router
