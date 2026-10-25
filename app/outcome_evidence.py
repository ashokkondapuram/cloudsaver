"""Signed collector attestations and exact financial math. Missing proof never means zero."""

from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib, hmac, json, os, re
from uuid import UUID
from app.focus import digest
from app.telemetry_contract import moment
from app.outcome_contracts import (
    Envelope,
    AuditProof,
    HealthProof,
    BillingProof,
    configuration,
)


def sources():
    raw = json.loads(os.getenv("CLOUDSAVER_EVIDENCE_SOURCES", "[]"))
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Invalid collector configuration")
    seen = set()
    result = []
    for value in raw:
        if not isinstance(value, dict) or set(value) != {
            "tenant_id",
            "source_id",
            "providers",
            "kinds",
            "scope_ids",
            "key_env",
        }:
            raise ValueError("Invalid collector grant")
        row = dict(value, tenant_id=str(UUID(value["tenant_id"])))
        key = row["tenant_id"], row["source_id"]
        if (
            key in seen
            or not re.fullmatch(r"[a-z0-9-]{1,60}", row["source_id"])
            or not re.fullmatch(
                r"CLOUDSAVER_EVIDENCE_KEY_[A-Z0-9_]{1,80}", row["key_env"]
            )
        ):
            raise ValueError("Invalid collector identity")
        for field, allowed in [
            ("providers", {"azure", "aws", "gcp", "kubernetes"}),
            ("kinds", {"audit", "billing", "slo"}),
        ]:
            if (
                not isinstance(row[field], list)
                or not row[field]
                or len(row[field]) > 4
                or not set(row[field]) <= allowed
            ):
                raise ValueError("Invalid collector scope")
        if (
            not isinstance(row["scope_ids"], list)
            or not 1 <= len(row["scope_ids"]) <= 100
            or any(
                not isinstance(s, str) or not 1 <= len(s) <= 128
                for s in row["scope_ids"]
            )
        ):
            raise ValueError("Invalid collector scope")
        seen.add(key)
        result.append(row)
    return result


def granted(source_id, tenant_id, provider, scope, kind):
    return any(
        s["source_id"] == source_id
        and s["tenant_id"] == tenant_id
        and provider in s["providers"]
        and scope in s["scope_ids"]
        and kind in s["kinds"]
        for s in sources()
    )


def validate_receipt(raw, signature, tenant, now):
    envelope = Envelope.model_validate(raw)
    if str(envelope.tenant_id) != tenant["tenant_id"]:
        raise ValueError("Receipt tenant mismatch")
    issued = moment(envelope.issued_at)
    if not issued or not -60 <= (now - issued).total_seconds() <= 300:
        raise ValueError("A freshly issued receipt is required")
    rows = [
        s
        for s in sources()
        if s["tenant_id"] == tenant["tenant_id"]
        and s["source_id"] == envelope.source_id
    ]
    if len(rows) != 1 or not granted(
        envelope.source_id,
        tenant["tenant_id"],
        envelope.provider,
        envelope.scope_id,
        envelope.kind,
    ):
        raise ValueError("Collector is not authorized")
    secret = os.getenv(rows[0]["key_env"], "")
    canonical = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if (
        len(canonical) > 16000
        or len(secret) < 32
        or not re.fullmatch(r"[a-f0-9]{64}", signature)
        or not hmac.compare_digest(
            hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(), signature
        )
    ):
        raise ValueError("Invalid collector signature")
    proof = {"audit": AuditProof, "billing": BillingProof, "slo": HealthProof}[
        envelope.kind
    ].model_validate(envelope.payload)
    normalized = proof.model_dump(mode="json")
    for field in ("occurred_at", "window_start", "window_end"):
        if field in normalized and not moment(normalized[field]):
            raise ValueError("Timezone-aware evidence is required")
    return (
        envelope,
        dict(schema_version=2, case_id=str(envelope.case_id), proof=normalized),
        hashlib.sha256(canonical).hexdigest(),
    )


def ledger_window(db, tid, case, currency, start, end):
    if not 0 < (end - start).days <= 90:
        raise ValueError("Invalid billing evidence window")
    begin = datetime.combine(start, time.min, timezone.utc)
    finish = datetime.combine(end, time.min, timezone.utc)
    rows = db.execute(
        "SELECT id,charge_id,fingerprint,period_start,period_end,billed_cost,effective_cost,charge_category FROM focus_charges "
        "WHERE tenant_id=%s AND provider=%s AND sub_account=%s AND resource_id=%s AND currency=%s AND period_start<%s AND period_end>%s ORDER BY id LIMIT 5001",
        (
            tid,
            case["provider"],
            case["scope_id"],
            case["resource_id"],
            currency,
            finish.isoformat(),
            begin.isoformat(),
        ),
    ).fetchall()
    if len(rows) > 5000:
        raise ValueError("Billing evidence exceeds the bounded resource window")
    selected = []
    total = Decimal(0)
    days = set()
    partial = False
    categories = {}
    for r in rows:
        a, b = moment(r[3]), moment(r[4])
        if not a or not b or a < begin or b > finish:
            partial = True
            continue
        value = Decimal(str(r[5]))
        total += value
        categories[r[7]] = categories.get(r[7], Decimal(0)) + value
        selected.append([str(r[0]), r[1], r[2]])
        if b - a == timedelta(days=1) and a.time() == time.min:
            days.add(a.date())
    return dict(
        period_start=str(start),
        period_end=str(end),
        billed_cost=format(total, "f") if selected else None,
        records=len(selected),
        observed_days=len(days),
        expected_days=(end - start).days,
        partial_records_excluded=partial,
        categories={k: format(v, "f") for k, v in categories.items()},
        digest=digest(selected),
        provider_reconciled=False,
    )


def ledger_pair(db, tid, case, proof):
    before = ledger_window(
        db,
        tid,
        case,
        proof["currency"],
        date.fromisoformat(proof["baseline_start"]),
        date.fromisoformat(proof["baseline_end"]),
    )
    after = ledger_window(
        db,
        tid,
        case,
        proof["currency"],
        date.fromisoformat(proof["post_start"]),
        date.fromisoformat(proof["post_end"]),
    )
    return dict(
        baseline=before, post=after, digest=digest([before["digest"], after["digest"]])
    )


def complete_scope(case, scan):
    return any(
        r.get("provider") == case["provider"]
        and r.get("scope_id") == case["scope_id"]
        and r.get("status") == "completed"
        and r.get("supported_inventory_complete") is True
        and case["payload"]["resource_type"].lower()
        in [str(t).lower() for t in r.get("supported_resource_types", [])]
        and (
            case["provider"] not in ("aws", "gcp")
            or case["payload"].get("region") in (r.get("regions") or [])
        )
        for r in scan.get("scope_results", [])
    )


def evaluate(case, scan, proofs, ledger, now):
    result = dict(
        status="insufficient_evidence",
        currency=case["payload"]["currency"],
        validated_run_rate_reduction=None,
        reconciled_financial_benefit=None,
        reasons=[],
        basis="signed_collectors_and_local_billing",
        automatic_execution=False,
    )

    def missing(code):
        return dict(result, reasons=[code])

    if not all(k in proofs for k in ("audit", "billing", "slo")):
        return missing("AUDIT_BILLING_AND_HEALTH_RECEIPTS_REQUIRED")
    audit, bill, health = (proofs[k]["proof"] for k in ("audit", "billing", "slo"))
    event = moment(audit["occurred_at"])
    approved = moment(case["payload"].get("approved_at"))
    observed = moment(scan.get("timestamp"))
    if not event or not approved or event < approved:
        return missing("ACTION_MUST_FOLLOW_SAVED_HUMAN_APPROVAL")
    if (
        scan.get("status") != "completed"
        or scan.get("data_origin") == "legacy_synthetic"
        or not observed
        or not 0 <= (now - observed).total_seconds() < 86400
        or observed <= event
    ):
        return missing("FRESH_COMPLETED_POST_CHANGE_SCAN_REQUIRED")
    if not complete_scope(case, scan):
        return missing("COMPLETE_SCOPE_OBSERVATION_REQUIRED")
    current = next(
        (
            r
            for r in scan.get("inventory", [])
            if r.get("cloud_provider", "azure") == case["provider"]
            and (
                r.get("resource_id", "").lower()
                if case["provider"] == "azure"
                else r.get("resource_id")
            )
            == case["resource_id"]
        ),
        None,
    )
    if case["payload"]["action"] == "retirement" and current is not None:
        return missing("RETIRED_RESOURCE_STILL_PRESENT")
    if case["payload"]["action"] == "rightsizing":
        if not case["payload"].get("configuration"):
            return missing("BASELINE_CONFIGURATION_REQUIRED")
        if current is None:
            return missing("RIGHTSIZED_RESOURCE_NOT_OBSERVED")
        after = digest(configuration(current))
        if (
            not configuration(current)
            or after == case["payload"]["configuration_digest"]
            or after != audit["after_configuration_digest"]
            or after != health["configuration_digest"]
        ):
            return missing("OBSERVED_CONFIGURATION_CHANGE_NOT_PROVEN")
    if audit["before_configuration_digest"] != case["payload"]["configuration_digest"]:
        return missing("AUDIT_BASELINE_CONFIGURATION_MISMATCH")
    expected = "delete" if case["payload"]["action"] == "retirement" else "resize"
    if audit["operation"] != expected:
        return missing("AUDIT_OPERATION_MISMATCH")
    a, b = moment(health["window_start"]), moment(health["window_end"])
    if (
        not a
        or not b
        or a < event
        or b > observed
        or b - a < timedelta(days=7)
        or not health["health_accepted"]
        or not health["utilization_accepted"]
    ):
        return missing("ACCEPTED_POST_CHANGE_HEALTH_AND_UTILIZATION_REQUIRED")
    dates = {
        k: date.fromisoformat(bill[k])
        for k in ("baseline_start", "baseline_end", "post_start", "post_end")
    }
    if (
        (dates["baseline_end"] - dates["baseline_start"]).days != 30
        or (dates["post_end"] - dates["post_start"]).days != 30
        or datetime.combine(dates["baseline_end"], time.min, timezone.utc) > approved
        or datetime.combine(dates["post_start"], time.min, timezone.utc) < event
        or dates["post_end"] > min(now.date(), observed.date())
        or a > datetime.combine(dates["post_start"], time.min, timezone.utc)
        or b < datetime.combine(dates["post_end"], time.min, timezone.utc)
    ):
        return missing("COMPARABLE_CLOSED_30_DAY_WINDOWS_REQUIRED")
    if (
        bill["currency"] != result["currency"]
        or not bill["coverage_complete"]
        or not bill["commitments_accounted_for"]
    ):
        return missing("COMPLETE_CURRENCY_AND_COMMITMENT_EVIDENCE_REQUIRED")
    before, after = (
        Decimal(bill["baseline_business_units"]),
        Decimal(bill["post_business_units"]),
    )
    if min(before, after) <= 0:
        return missing("POSITIVE_BUSINESS_VOLUME_REQUIRED")
    with localcontext() as context:
        context.prec = 50
        ratio = after / before
        if not Decimal(".25") <= ratio <= Decimal("4"):
            return missing("DEMAND_CHANGE_EXCEEDS_COMPARABILITY_LIMIT")
        extra = Decimal(bill["added_recurring_cost"]) + Decimal(
            bill["retained_commitment_cost"]
        )
        recurring = (
            Decimal(bill["baseline_recurring_cost"]) * ratio
            - Decimal(bill["post_recurring_cost"])
            - extra
        )
        if abs(recurring) > Decimal("1e15"):
            return missing("FINANCIAL_AMOUNT_OUT_OF_BOUNDS")
        result.update(
            status="run_rate_validated",
            validated_run_rate_reduction=format(
                recurring.quantize(Decimal(".00000001")), "f"
            ),
            business_unit=bill["business_unit"],
            demand_ratio=format(ratio, "f"),
            period_start=bill["post_start"],
            period_end=bill["post_end"],
        )
        result["calculation"] = {
            k: bill[k]
            for k in (
                "baseline_recurring_cost",
                "post_recurring_cost",
                "added_recurring_cost",
                "retained_commitment_cost",
                "baseline_billed_cost",
                "post_billed_cost",
                "transition_cost",
                "counterfactual_adjustment",
                "baseline_business_units",
                "post_business_units",
            )
        }
        if (
            not bill["provider_reconciled"]
            or not bill["credits_accounted_for"]
            or not bill["invoice_reference"]
        ):
            return dict(
                result,
                reasons=["PROVIDER_RECONCILIATION_AND_CREDIT_ACCOUNTING_REQUIRED"],
            )
        if (
            not ledger
            or bill["ledger_digest"] != ledger["digest"]
            or any(
                ledger[k]["partial_records_excluded"]
                or ledger[k]["billed_cost"] is None
                for k in ("baseline", "post")
            )
            or Decimal(ledger["baseline"]["billed_cost"])
            != Decimal(bill["baseline_billed_cost"])
            or Decimal(ledger["post"]["billed_cost"])
            != Decimal(bill["post_billed_cost"])
        ):
            return dict(
                result,
                reasons=["LOCAL_BILLING_LEDGER_MUST_MATCH_SIGNED_RECONCILIATION"],
            )
        benefit = (
            Decimal(bill["baseline_billed_cost"]) * ratio
            - Decimal(bill["post_billed_cost"])
            - extra
            - Decimal(bill["transition_cost"])
            + Decimal(bill["counterfactual_adjustment"])
        )
        if max(abs(benefit), abs(recurring)) > Decimal("1e15"):
            return missing("FINANCIAL_AMOUNT_OUT_OF_BOUNDS")
        return dict(
            result,
            status="financially_reconcilable",
            reconciled_financial_benefit=format(
                benefit.quantize(Decimal(".00000001")), "f"
            ),
            ledger_digest=ledger["digest"],
            warning="Relies on authorized collector attestations and exact imported charges. This is not an independent invoice audit.",
        )
