"""Deterministic action-safety rules AG-* (pilot). Unknown mandatory evidence blocks."""
from __future__ import annotations

RULE_VERSION = "0.1"
PASS, FAIL, UNKNOWN, NA = "pass", "fail", "unknown", "not_applicable"


def _tri(value, fail_when):
    if value is None:
        return UNKNOWN
    return FAIL if fail_when(value) else PASS


def _cost(e):
    if e.get("claims_positive_benefit") is None or e.get("absorption_proven") is None:
        return UNKNOWN
    if e["claims_positive_benefit"] and not e["absorption_proven"] and e.get("fees_remain", True):
        return FAIL
    return PASS


def _id(e):
    if e.get("ip_dependency_confirmed"):
        return FAIL
    return UNKNOWN if e.get("external_owner_known") is not True and e.get("ip_dependency_confirmed") is None else PASS


def _ha(e):
    if e.get("removes_quorum_member") is True or e.get("violates_capacity_floor") is True:
        return FAIL
    if e.get("removes_quorum_member") is None or e.get("violates_capacity_floor") is None:
        return UNKNOWN
    return PASS


def _dr(e):
    return _tri(e.get("is_standby_or_replica"), bool)


def _ret(e):
    return _tri(e.get("active_hold"), bool)


def _rec(e):
    if not e.get("destructive"):
        return NA
    return _tri(e.get("restore_verified"), lambda v: not v)


def _perf(e):
    if not e.get("capacity_reduction"):
        return NA
    if e.get("memory_history_days") is None or e.get("valid_sample_ratio") is None:
        return UNKNOWN
    if e["memory_history_days"] < 14 or e["valid_sample_ratio"] < 0.95:
        return UNKNOWN
    return FAIL if e.get("insufficient_headroom") else PASS


def _ops(e):
    ok = [e.get("owner"), e.get("responder_reachable"), e.get("rollback_supported")]
    if any(v is None for v in ok):
        return UNKNOWN
    return PASS if all(ok) else FAIL


RULES = {
    "AG-COST-01": _cost, "AG-ID-01": _id, "AG-HA-01": _ha, "AG-DR-01": _dr,
    "AG-RET-01": _ret, "AG-REC-01": _rec, "AG-PERF-01": _perf, "AG-OPS-01": _ops,
}


def evaluate(action: dict, evidence: dict) -> dict:
    """Return findings and an eligibility decision. Never means execution approved."""
    findings = {rid: fn(evidence) for rid, fn in RULES.items()}
    if not action.get("supported", False):
        decision = "unsupported"
    elif FAIL in findings.values():
        decision = "blocked"
    elif UNKNOWN in findings.values():
        decision = "evidence_required"
    else:
        decision = "eligible_for_review"
    return {"rule_version": RULE_VERSION, "action": action.get("id"),
            "findings": findings, "decision": decision}
