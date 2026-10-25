from decimal import Decimal
import pytest

from app.control_plane import action_safety as ag
from app.control_plane.financial_scenarios import ScenarioInput, dedupe_commitments, evaluate, money


def test_covered_rightsize_saves_zero():
    r = evaluate(ScenarioInput("USD", "600", "200", "100", absorption_proven=False))
    assert Decimal(r["net_recurring_benefit"]) == 0


def test_proven_absorption_saves():
    r = evaluate(ScenarioInput("USD", "600", "200", "100", absorption_proven=True))
    assert r["baseline_payable"] == "800" and r["post_payable"] == "700"
    assert r["net_recurring_benefit"] == "100"


def test_missing_coverage_is_unknown():
    assert evaluate(ScenarioInput("USD", None, "200", None))["status"] == "unknown"


def test_float_money_rejected():
    with pytest.raises(ValueError):
        money(1.5)


def test_dedupe_shared_commitment():
    s = {"billing_identity": "b1", "commitment_id": "c1"}
    assert len(dedupe_commitments([s, dict(s)])) == 1


FULL = dict(claims_positive_benefit=False, absorption_proven=False, ip_dependency_confirmed=False,
            external_owner_known=True, removes_quorum_member=False, violates_capacity_floor=False,
            is_standby_or_replica=False, active_hold=False, destructive=False, capacity_reduction=True,
            memory_history_days=20, valid_sample_ratio=0.99, insufficient_headroom=False,
            owner="o", responder_reachable=True, rollback_supported=True)


def test_all_pass_is_eligible_for_review_only():
    assert ag.evaluate({"id": "a", "supported": True}, FULL)["decision"] == "eligible_for_review"


def test_standby_blocks():
    e = dict(FULL, is_standby_or_replica=True)
    assert ag.evaluate({"id": "a", "supported": True}, e)["decision"] == "blocked"


def test_missing_memory_is_unknown_not_pass():
    e = dict(FULL, memory_history_days=None)
    assert ag.evaluate({"id": "a", "supported": True}, e)["decision"] == "evidence_required"


def test_unsupported_action():
    assert ag.evaluate({"id": "a", "supported": False}, FULL)["decision"] == "unsupported"
