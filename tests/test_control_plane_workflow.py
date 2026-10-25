import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone

from app.control_plane.commitment_expiry import due_reminders
from app.control_plane.gitops_checks import (CheckRecord, DeliveryDeduper, check_conclusion,
                                              check_current, verify_signature)
from app.control_plane.plans import Approval, PlanVersion, approval_valid, detect_conflicts


def plan(pid="p1", v=1, **kw):
    return PlanVersion(pid, v, ("vm1",), {"sku": "D2"}, "pol", "ev", **kw)


def test_conflicts():
    a = plan("a", exclusive_targets=("lb",), consumes_ha_headroom=("set1",), skus={"vm1": "D2"})
    b = plan("b", exclusive_targets=("lb",), consumes_ha_headroom=("set1",), skus={"vm1": "D4"})
    types = {c["type"] for c in detect_conflicts([a, b])}
    assert types == {"shared_resource_claimed", "ha_headroom_contention", "exclusive_sku_additive"}


def test_approval_bound_to_exact_version():
    p1 = plan(v=1)
    ap = Approval(p1.identity(), "alice", datetime.now(timezone.utc) + timedelta(hours=1), True)
    assert approval_valid(ap, p1)[0]
    assert not approval_valid(ap, plan(v=2))[0]
    assert not approval_valid(ap, p1, revoked=frozenset({"alice"}))[0]
    old = Approval(p1.identity(), "alice", datetime.now(timezone.utc) - timedelta(seconds=1), True)
    assert not approval_valid(old, p1)[0]
    assert not approval_valid(Approval(p1.identity(), "bot", ap.expires_at, False), p1)[0]


def test_signature_and_dedupe():
    body, secret = b"{}", b"s3cret"
    sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, sig)
    assert not verify_signature(secret, body, "sha256=bad")
    assert not verify_signature(secret, body, None)
    d = DeliveryDeduper()
    assert d.first_time("x") and not d.first_time("x")


def test_check_revision_binding():
    r = CheckRecord(1, "b", "h1", "pd", "pol", "ev", "eligible_for_review", True)
    assert check_conclusion(r) == "success"
    assert check_current(r, 1, "b", "h1", "pd", "pol", "ev")
    assert not check_current(r, 1, "b", "h2", "pd", "pol", "ev")
    assert check_conclusion(CheckRecord(1, "b", "h1", "pd", "pol", "ev", "eligible_for_review", False)) == "failure"
    assert check_conclusion(CheckRecord(1, "b", "h1", "pd", "pol", "ev", "blocked", True)) == "failure"


def test_expiry_reminders():
    cs = [{"commitment_id": "c1", "end_date": date(2026, 12, 1)},
          {"commitment_id": "c2", "end_date": date(2027, 6, 1)}]
    out = due_reminders(cs, date(2026, 10, 25))
    assert [o["commitment_id"] for o in out] == ["c1"] and out[0]["threshold_days"] == 60
    assert due_reminders(cs, date(2026, 10, 25), already_sent={("c1", 60)}) == []
