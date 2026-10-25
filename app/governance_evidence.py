"""Local evidence evaluation and scoped collector attestations; no external processing."""

from datetime import timedelta
import hashlib, hmac, json, os, re
from uuid import UUID
from app.focus import digest
from app.telemetry_contract import moment
from app.governance_contracts import (
    Envelope,
    Implementation,
    Verification,
    Compensation,
    Correction,
)

MAX_AGE = timedelta(hours=24)


def sources():
    values = json.loads(os.getenv("CLOUDSAVER_GOVERNANCE_SOURCES", "[]"))
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError("Invalid governance sources")
    seen = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "tenant_id",
            "source_id",
            "providers",
            "scope_ids",
            "kinds",
            "key_env",
        }:
            raise ValueError("Invalid governance source grant")
        if (
            str(UUID(value["tenant_id"])) != value["tenant_id"]
            or not re.fullmatch(r"[a-z0-9-]{1,60}", value["source_id"])
            or not re.fullmatch(
                r"CLOUDSAVER_GOVERNANCE_KEY_[A-Z0-9_]{1,80}", value["key_env"]
            )
        ):
            raise ValueError("Invalid governance source identity")
        key = value["tenant_id"], value["source_id"]
        if key in seen:
            raise ValueError("Duplicate governance source")
        seen.add(key)
        if not isinstance(value["providers"], list) or value["providers"] != ["azure"]:
            raise ValueError("Only the reviewed Azure control is supported")
        if (
            not isinstance(value["kinds"], list)
            or not value["kinds"]
            or not set(value["kinds"])
            <= {"implementation", "verification", "compensation", "correction"}
        ):
            raise ValueError("Invalid evidence kinds")
        if (
            not isinstance(value["scope_ids"], list)
            or not 1 <= len(value["scope_ids"]) <= 100
            or any(
                not isinstance(s, str) or not s or len(s) > 128
                for s in value["scope_ids"]
            )
        ):
            raise ValueError("Invalid evidence scopes")
    return values


def granted(source, tenant, finding, kind):
    return any(
        v["source_id"] == source
        and v["tenant_id"] == tenant
        and finding["provider"] in v["providers"]
        and finding["scope_id"] in v["scope_ids"]
        and kind in v["kinds"]
        for v in sources()
    )


def receipt(raw, signature, tenant, finding, now, *, require_recent_issuance=True):
    env = Envelope.model_validate(raw)
    issued = moment(env.issued_at)
    if (
        str(env.tenant_id) != tenant
        or str(env.finding_id) != finding["id"]
        or not issued
        or require_recent_issuance
        and not -60 <= (now - issued).total_seconds() <= 300
    ):
        raise ValueError("Receipt binding or freshness is invalid")
    source = next(
        (
            v
            for v in sources()
            if v["source_id"] == env.source_id and v["tenant_id"] == tenant
        ),
        None,
    )
    if not source or not granted(env.source_id, tenant, finding, env.kind):
        raise ValueError("Collector is not granted this target")
    canonical = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    secret = os.getenv(source["key_env"], "")
    if (
        len(canonical) > 16000
        or len(secret) < 32
        or not re.fullmatch(r"[a-f0-9]{64}", signature)
        or not hmac.compare_digest(
            hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(), signature
        )
    ):
        raise ValueError("Invalid collector signature")
    proof = (
        {
            "implementation": Implementation,
            "verification": Verification,
            "compensation": Compensation,
            "correction": Correction,
        }[env.kind]
        .model_validate(env.payload)
        .model_dump(mode="json")
    )
    for key in ("occurred_at", "observed_at", "valid_until", "evaluated_at"):
        if key in proof and not moment(proof[key]):
            raise ValueError("Explicit timezone is required")
    for field in ("occurred_at", "observed_at", "evaluated_at"):
        if field in proof and moment(proof[field]) > min(now, issued):
            raise ValueError("A collector cannot attest a future observation")
    return env, proof, hashlib.sha256(canonical).hexdigest()


def evaluate(resource, scan, context, policy, now):
    observed = moment(scan.get("timestamp"))
    kind = str(resource.get("resource_type", "")).lower()
    flag = (resource.get("evidence") or {}).get("allow_blob_public_access")
    config = {"allow_blob_public_access": flag if type(flag) is bool else None}
    state = digest(
        dict(configuration=config, context=context, control_version=policy["version"])
    )
    result = "unknown"
    reason = "CONFIGURATION_OR_CONTEXT_UNOBSERVED"
    if kind != "microsoft.storage/storageaccounts":
        result = "not_applicable"
        reason = "RESOURCE_TYPE_OUTSIDE_CONTROL"
    elif context["environment"] == "nonproduction" or context["classification"] in (
        "internal",
        "public",
    ):
        result = "not_applicable"
        reason = "HUMAN_REVIEWED_CONTEXT_OUTSIDE_CONTROL_SCOPE"
    elif (
        context["environment"] == "production"
        and context["classification"] == "customer_data"
        and type(flag) is bool
    ):
        result = "fail" if flag else "pass"
        reason = (
            "ACCOUNT_PERMITS_PUBLIC_BLOB_ACCESS"
            if flag
            else "ACCOUNT_DISALLOWS_PUBLIC_BLOB_ACCESS"
        )
    if (
        not observed
        or not timedelta(0) <= now - observed <= MAX_AGE
        or scan.get("status") != "completed"
        or scan.get("data_origin") == "legacy_synthetic"
    ):
        result = "unknown"
        reason = "FRESH_COMPLETED_OBSERVATION_REQUIRED"
    return dict(
        target=dict(
            provider=resource.get("cloud_provider", "azure"),
            scope_id=resource.get("scope_id") or resource.get("subscription_id"),
            resource_id=str(resource.get("resource_id", "")).lower(),
        ),
        result=result,
        reason=reason,
        state_digest=state,
        scan_id=scan["scan_id"],
        observed_at=scan.get("timestamp"),
        configuration=config,
        context=context,
        control_version=policy["version"],
        scope="production_customer_data_storage",
        confidence="observed_configuration_and_human_context"
        if result in ("pass", "fail")
        else "incomplete_or_inapplicable",
        limitation="Account permission is not proof that a container is public or that customer data was accessed.",
        policy_digest=digest(policy),
    )


def fresh(assessment, now):
    at = moment(assessment.get("observed_at"))
    return bool(at and timedelta(0) <= now - at <= MAX_AGE)
