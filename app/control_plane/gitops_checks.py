"""Revision-bound GitOps check records and webhook signature validation."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

MAX_BODY = 1_000_000


def verify_signature(secret: bytes, raw_body: bytes, header: str | None) -> bool:
    """GitHub X-Hub-Signature-256 validation on the raw, bounded request body."""
    if not header or not header.startswith("sha256=") or len(raw_body) > MAX_BODY:
        return False
    expected = "sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


class DeliveryDeduper:
    def __init__(self):
        self._seen: set[str] = set()

    def first_time(self, delivery_id: str) -> bool:
        if delivery_id in self._seen:
            return False
        self._seen.add(delivery_id)
        return True


@dataclass(frozen=True)
class CheckRecord:
    repo_id: int
    base_sha: str
    head_sha: str
    plan_digest: str
    policy_digest: str
    evidence_digest: str
    decision: str
    trusted_plan: bool

    def key(self) -> tuple:
        return (self.repo_id, self.base_sha, self.head_sha, self.plan_digest,
                self.policy_digest, self.evidence_digest)


def check_conclusion(rec: CheckRecord) -> str:
    """Only a trusted plan with an eligible decision passes; skipped/neutral never satisfies."""
    if not rec.trusted_plan:
        return "failure"
    return "success" if rec.decision == "eligible_for_review" else "failure"


def check_current(rec: CheckRecord, repo_id: int, base_sha: str, head_sha: str,
                  plan_digest: str, policy_digest: str, evidence_digest: str) -> bool:
    """A stale green check is not a current permit."""
    return rec.key() == (repo_id, base_sha, head_sha, plan_digest, policy_digest, evidence_digest)
