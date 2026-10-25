"""Regression checks for fail-closed evidence, exact approval and strict authority inputs."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac

import pytest
from pydantic import ValidationError

from app.control_plane import action_safety
from app.control_plane.contracts import ActionAssessmentRequest, FinancialScenarioRequest
from app.control_plane.financial_scenarios import ScenarioInput, evaluate
from app.control_plane.gitops_checks import CheckRecord, check_conclusion, verify_signature
from app.control_plane.plans import Approval, PlanVersion, approval_valid


FULL = dict(claims_positive_benefit=False, absorption_proven=False,
            ip_dependency_confirmed=False, external_owner_known=True,
            removes_quorum_member=False, violates_capacity_floor=False,
            is_standby_or_replica=False, active_hold=False, destructive=False,
            capacity_reduction=True, memory_history_days=20, valid_sample_ratio=.99,
            insufficient_headroom=False, owner="owner", responder_reachable=True,
            rollback_supported=True)
ACTION = {"id": "vm-rightsize", "supported": True}


def test_unknown_external_owner_requires_evidence():
    result = action_safety.evaluate(ACTION, dict(FULL, external_owner_known=None))
    assert result["findings"]["AG-ID-01"] == "unknown"
    assert result["decision"] != "eligible_for_review"


def test_missing_headroom_requires_evidence():
    evidence = dict(FULL)
    evidence.pop("insufficient_headroom")
    result = action_safety.evaluate(ACTION, evidence)
    assert result["findings"]["AG-PERF-01"] == "unknown"


@pytest.mark.parametrize("field,value", [
    ("memory_history_days", float("nan")),
    ("valid_sample_ratio", float("nan")),
    ("valid_sample_ratio", 1.5),
])
def test_invalid_utilization_evidence_cannot_pass(field, value):
    try:
        result = action_safety.evaluate(ACTION, dict(FULL, **{field: value}))
    except (TypeError, ValueError):
        return
    assert result["findings"]["AG-PERF-01"] != "pass"


def test_missing_action_safety_applicability_is_unknown():
    evidence = dict(FULL)
    evidence.pop("capacity_reduction")
    assert action_safety.evaluate(ACTION, evidence)["findings"]["AG-PERF-01"] != "not_applicable"


def test_contract_rejects_string_supported_boolean():
    with pytest.raises(ValidationError):
        ActionAssessmentRequest(idempotency_key="test-key-0001", action_id="resize", supported="true")


def test_contract_rejects_string_absorption_boolean():
    with pytest.raises(ValidationError):
        FinancialScenarioRequest(idempotency_key="test-key-0001", currency="USD", absorption_proven="true")


def test_approval_binds_sku_conflict_and_capacity_metadata():
    common = dict(plan_id="p", version=1, targets=("vm",), parameters={},
                  policy_digest="policy", evidence_digest="evidence")
    original = PlanVersion(**common, skus={"vm": "D2"}, exclusive_targets=("disk",),
                           consumes_ha_headroom=("cluster",))
    edited = PlanVersion(**common, skus={"vm": "D8"}, exclusive_targets=(),
                         consumes_ha_headroom=())
    approval = Approval(original.identity(), "reviewer", datetime.now(timezone.utc) + timedelta(hours=1), True)
    assert approval_valid(approval, edited)[0] is False


def test_check_requires_a_boolean_trusted_attestation():
    rec = CheckRecord(1, "base", "head", "plan", "policy", "evidence", "eligible_for_review", "false")
    assert check_conclusion(rec) == "failure"


def test_webhook_rejects_unconfigured_empty_secret():
    body = b"{}"
    header = "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()
    assert verify_signature(b"", body, header) is False


def test_financial_math_does_not_drop_accepted_fractional_money():
    fee = "10000000000000000000000000000"
    with pytest.raises(ValueError):
        evaluate(ScenarioInput("USD", fee, "0.01", "0.01", absorption_proven=True))


def test_negative_net_benefit_is_preserved():
    result = evaluate(ScenarioInput("USD", "600", "200", "100", True, new_recurring="150"))
    assert Decimal(result["net_recurring_benefit"]) == -50


def test_unknown_charge_coverage_stays_unknown():
    assert evaluate(ScenarioInput("USD", None, "200", "100", True))["status"] == "unknown"


def test_plan_parameter_change_invalidates_approval():
    original = PlanVersion("p", 1, ("vm",), {"sku": "D2"}, "policy", "evidence")
    edited = PlanVersion("p", 1, ("vm",), {"sku": "D8"}, "policy", "evidence")
    approval = Approval(original.identity(), "reviewer", datetime.now(timezone.utc) + timedelta(hours=1), True)
    assert approval_valid(approval, edited)[0] is False
