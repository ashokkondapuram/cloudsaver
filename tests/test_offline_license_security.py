from uuid import uuid4
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient


def test_bearer_license_cannot_be_a_human_approver():
    from app.control_plane_api import _require_human_approver
    from app.outcome_contracts import human
    tenant={'tenant_id':str(uuid4()),'roles':['TenantAdmin'],'subject_type':'license','subject_id':str(uuid4())}
    assert not human(tenant)
    with pytest.raises(HTTPException) as exc:_require_human_approver(tenant)
    assert exc.value.status_code==403


def test_bearer_license_cannot_authorize_privacy_erasure_or_hold():
    from app.data_governance_api import create_router
    tenant={'tenant_id':str(uuid4()),'roles':['TenantAdmin'],'subject_type':'license','subject_id':str(uuid4())}
    app=FastAPI();app.include_router(create_router(object(),lambda:tenant,governor=object()))
    with TestClient(app) as client:
        response=client.post(f'/api/v1/ai/governance/records/{uuid4()}/erase',json={'review_reference':'SEC-123'})
        assert response.status_code==403
