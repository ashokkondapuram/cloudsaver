"""Provider-scoped keys can read governance and outcomes in their grant."""
import pytest
from fastapi import HTTPException

from app.data_scope import resource_visible
from app.provider_access import enforce_route
from tests.test_enterprise import workspace

AWS_ACCOUNT = "123456789012"


def aws_workspace():
    return dict(
        workspace(),
        aws_accounts=[
            {
                "account_id": AWS_ACCOUNT,
                "region": "us-east-1",
                "role_arn": f"arn:aws:iam::{AWS_ACCOUNT}:role/Reader",
            }
        ],
    )


@pytest.fixture
def limited_aws_tenant():
    return dict(aws_workspace(), allowed_providers=["aws"])


def test_enforce_route_allows_scoped_governance_and_outcomes_reads(limited_aws_tenant):
    for method, path in (
        ("GET", "/api/v1/governance/summary"),
        ("GET", "/api/v1/governance/findings"),
        ("GET", "/api/v1/governance/risks"),
        ("GET", "/api/v1/governance/exceptions"),
        ("GET", "/api/v1/governance/controls"),
        ("GET", "/api/v1/outcomes/summary"),
        ("GET", "/api/v1/outcomes/cases"),
        ("GET", "/api/v1/outcomes/anomalies"),
    ):
        enforce_route(method, path, limited_aws_tenant, ["azure", "aws"])


def test_enforce_route_still_blocks_governance_admin_routes(limited_aws_tenant):
    with pytest.raises(HTTPException) as error:
        enforce_route("GET", "/api/v1/governance/access", limited_aws_tenant, ["azure", "aws"])
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        enforce_route("POST", "/api/v1/governance/monitor", limited_aws_tenant, ["azure", "aws"])
    assert error.value.status_code == 403


def test_resource_visible_matches_provider_grant(limited_aws_tenant):
    assert resource_visible(limited_aws_tenant, "aws", AWS_ACCOUNT)
    assert not resource_visible(limited_aws_tenant, "azure", workspace()["subscription_ids"][0])
