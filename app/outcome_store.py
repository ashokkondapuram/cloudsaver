"""Accountable optimization lifecycle on the existing tenant-isolated savings records."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from app.enterprise_store import decode
from app.focus import digest, authorized
from app.principals import actor, visible
from app.outcome_contracts import configuration, utilization, human
from app import outcome_evidence as evidence

COLUMNS = "id,provider,scope_id,resource_id,baseline_scan_id,state,version,payload,verification,created_at,updated_at"


class OutcomeConflict(ValueError):
    pass


def scope_allowed(tenant, provider, scope):
    if provider not in ("azure", "aws", "gcp", "kubernetes"):
        return False
    return (
        scope in {r["cluster_id"] for r in tenant.get("kubernetes_clusters", [])}
        if provider == "kubernetes"
        else authorized(provider, scope, tenant)
    ) and visible(dict(provider=provider, scope_id=scope), tenant)


class Outcomes:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _case(self, db, tid, id):
        row = db.execute(
            "SELECT " + COLUMNS + " FROM savings_cases WHERE tenant_id=%s AND id=%s",
            (tid, id),
        ).fetchone()
        if row is None:
            return None
        value = dict(zip(COLUMNS.split(","), row))
        for k in ("id", "baseline_scan_id", "created_at", "updated_at"):
            value[k] = str(value[k])
        value["payload"] = decode(value["payload"])
        value["verification"] = (
            decode(value["verification"]) if value["verification"] is not None else None
        )
        value["legacy"] = value["payload"].get("schema_version") != 2
        return value

    def _owned(self, db, tenant, id):
        case = self._case(db, tenant["tenant_id"], id)
        return (
            case
            if case and scope_allowed(tenant, case["provider"], case["scope_id"])
            else None
        )

    def _event(self, db, tenant, case, action, data):
        db.execute(
            "INSERT INTO savings_case_events(id,tenant_id,case_id,action,version,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                str(uuid4()),
                tenant["tenant_id"],
                case["id"],
                action,
                case["version"],
                db.json(data),
                actor(tenant),
                self.clock().isoformat(),
            ),
        )

    def _save(self, db, tenant, case, state, payload, verification, action, note):
        result = db.execute(
            "UPDATE savings_cases SET state=%s,version=version+1,payload=%s,verification=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=%s",
            (
                state,
                db.json(payload),
                db.json(verification) if verification is not None else None,
                self.clock().isoformat(),
                tenant["tenant_id"],
                case["id"],
                case["version"],
            ),
        )
        if result.rowcount != 1:
            raise OutcomeConflict("Case changed. Refresh before updating.")
        new = self._case(db, tenant["tenant_id"], case["id"])
        self._event(
            db,
            tenant,
            new,
            action,
            dict(
                before=case["state"], after=state, note=note, verification=verification
            ),
        )
        return new

    def create(self, tenant, scan, resource, body):
        tid = tenant["tenant_id"]
        provider = resource.get("cloud_provider", "azure")
        scope = resource.get("scope_id") or resource.get("subscription_id")
        rid = (
            resource["resource_id"].lower()
            if provider == "azure"
            else resource["resource_id"]
        )
        if not scope_allowed(tenant, provider, scope):
            raise ValueError("Resource is outside the current workspace scope")
        fingerprint = digest(body.model_dump(mode="json"))
        now = self.clock().isoformat()
        with self.store.transaction(tid, write=True) as db:
            prior = db.execute(
                "SELECT id,fingerprint FROM savings_cases WHERE tenant_id=%s AND request_key=%s",
                (tid, str(body.request_key)),
            ).fetchone()
            if prior:
                if prior[1] != fingerprint:
                    raise OutcomeConflict(
                        "Request key already belongs to a different case"
                    )
                return self._case(db, tid, str(prior[0]))
            if (
                db.execute(
                    "SELECT count(*) FROM savings_cases WHERE tenant_id=%s", (tid,)
                ).fetchone()[0]
                >= 1000
            ):
                raise OutcomeConflict("The workspace case limit is 1000")
            conf = configuration(resource)
            amounts = [
                Decimal(str(f["estimated_monthly_waste_usd"]))
                for f in scan.get("findings", [])
                if (
                    f["resource_id"].lower()
                    if provider == "azure"
                    else f["resource_id"]
                )
                == rid
                and f.get("estimated_monthly_waste_usd") is not None
            ]
            estimate = max(amounts) if amounts and body.currency == "USD" else None
            payload = dict(
                schema_version=2,
                resource_name=resource.get("resource_name", rid),
                resource_type=resource["resource_type"],
                region=resource.get("region"),
                action=body.action,
                proposal=body.proposal,
                currency=body.currency,
                estimated_opportunity=format(estimate, "f")
                if estimate is not None
                else None,
                estimate_basis="saved_retail_opportunity_not_billing_or_realized_savings",
                configuration=conf,
                configuration_complete=False,
                configuration_digest=digest(conf),
                utilization=utilization(resource),
                baseline_observed_at=scan["timestamp"],
                baseline_rule_ids=sorted(
                    {
                        f["rule_id"]
                        for f in scan.get("findings", [])
                        if (
                            f["resource_id"].lower()
                            if provider == "azure"
                            else f["resource_id"]
                        )
                        == rid
                    }
                ),
            )
            end = evidence.moment(scan["timestamp"]).date()
            payload["baseline_billing"] = evidence.ledger_window(
                db,
                tid,
                dict(provider=provider, scope_id=scope, resource_id=rid),
                body.currency,
                end - timedelta(days=30),
                end,
            )
            id = str(uuid4())
            db.execute(
                "INSERT INTO savings_cases(id,tenant_id,provider,scope_id,resource_id,baseline_scan_id,request_key,fingerprint,state,version,payload,actor,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'detected',1,%s,%s,%s,%s)",
                (
                    id,
                    tid,
                    provider,
                    scope,
                    rid,
                    scan["scan_id"],
                    str(body.request_key),
                    fingerprint,
                    db.json(payload),
                    actor(tenant),
                    now,
                    now,
                ),
            )
            case = self._case(db, tid, id)
            self._event(
                db,
                tenant,
                case,
                "detected",
                dict(scan_id=scan["scan_id"], baseline_digest=digest(payload)),
            )
            return case

    def cases(self, tenant):
        with self.store.transaction(tenant["tenant_id"]) as db:
            ids = db.execute(
                "SELECT id FROM savings_cases WHERE tenant_id=%s ORDER BY updated_at DESC,id DESC LIMIT 1000",
                (tenant["tenant_id"],),
            ).fetchall()
            return [c for row in ids if (c := self._owned(db, tenant, str(row[0])))]

    def receipts(self, db, tenant, case):
        rows = db.execute(
            "SELECT id,source_id,kind,payload,issued_at FROM savings_evidence_receipts WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND resource_id=%s ORDER BY created_at DESC,issued_at DESC,id DESC LIMIT 200",
            (
                tenant["tenant_id"],
                case["provider"],
                case["scope_id"],
                case["resource_id"],
            ),
        ).fetchall()
        result = {}
        for row in rows:
            payload = decode(row[3])
            if (
                row[2] not in result
                and payload.get("schema_version") == 2
                and payload.get("case_id") == case["id"]
                and evidence.granted(
                    row[1],
                    tenant["tenant_id"],
                    case["provider"],
                    case["scope_id"],
                    row[2],
                )
            ):
                result[row[2]] = dict(
                    id=str(row[0]),
                    source_id=row[1],
                    kind=row[2],
                    issued_at=str(row[4]),
                    proof=payload["proof"],
                )
        return result

    def detail(self, tenant, id):
        with self.store.transaction(tenant["tenant_id"]) as db:
            case = self._owned(db, tenant, id)
            if case is None:
                return None
            events = db.execute(
                "SELECT action,version,payload,actor,created_at FROM savings_case_events WHERE tenant_id=%s AND case_id=%s ORDER BY version DESC LIMIT 200",
                (tenant["tenant_id"], id),
            ).fetchall()
            case["events"] = [
                dict(
                    action=r[0],
                    version=r[1],
                    payload=decode(r[2]),
                    actor=r[3],
                    created_at=str(r[4]),
                )
                for r in reversed(events)
            ]
            receipts = self.receipts(db, tenant, case) if not case["legacy"] else {}
            case["evidence"] = [
                dict(
                    id=v["id"],
                    kind=v["kind"],
                    source_id=v["source_id"],
                    issued_at=v["issued_at"],
                )
                for v in receipts.values()
            ]
            result = case.get("verification") or {}
            supported = bool(result)
            reason = None
            expected = result.get("receipt_ids", {})
            if expected and any(
                k not in receipts or receipts[k]["id"] != id
                for k, id in expected.items()
            ):
                supported = False
                reason = "COLLECTOR_GRANT_OR_EVIDENCE_CHANGED"
            case["run_rate_evidence_current"] = bool(
                result.get("validated_run_rate_reduction") is not None
                and supported
                and case["state"] in ("validated", "financially_reconciled")
            )
            if result.get("reconciled_financial_benefit") is not None and supported:
                ledger = evidence.ledger_pair(
                    db, tenant["tenant_id"], case, receipts["billing"]["proof"]
                )
                if ledger["digest"] != result.get("ledger_digest"):
                    supported = False
                    reason = "BILLING_LEDGER_CHANGED_RECONCILIATION_REQUIRED"
            case["financial_evidence_current"] = bool(
                result.get("reconciled_financial_benefit") is not None and supported
            )
            case["financial_uncertainty_reason"] = reason
            case["financial_claims"] = self._claims(db, tenant, case)

            return case

    def _claims(self, db, tenant, case):
        rows = db.execute(
            "SELECT id,currency,period_start,period_end,amount,ledger_digest,receipt_id,revision,evidence FROM savings_financial_claims WHERE tenant_id=%s AND case_id=%s ORDER BY revision DESC,created_at DESC LIMIT 101",
            (tenant["tenant_id"], case["id"]),
        ).fetchall()
        if len(rows) > 100:
            raise ValueError(
                "More than 100 claim revisions requires a reviewed larger-history reporting path"
            )
        candidates = db.execute(
            "SELECT id,source_id,kind,payload FROM savings_evidence_receipts WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND resource_id=%s ORDER BY created_at DESC,issued_at DESC,id DESC LIMIT 200",
            (
                tenant["tenant_id"],
                case["provider"],
                case["scope_id"],
                case["resource_id"],
            ),
        ).fetchall()
        latest = {}
        by_id = {}

        def identity(kind, proof):
            if kind == "billing":
                return (kind, proof["currency"], proof["post_start"], proof["post_end"])
            if kind == "slo":
                return (kind, proof["window_start"], proof["window_end"])
            return (kind, proof["event_id"])

        for r in candidates:
            payload = decode(r[3])
            if (
                payload.get("schema_version") != 2
                or payload.get("case_id") != case["id"]
                or not evidence.granted(
                    r[1], tenant["tenant_id"], case["provider"], case["scope_id"], r[2]
                )
            ):
                continue
            proof = payload["proof"]
            key = identity(r[2], proof)
            by_id[str(r[0])] = (r[2], proof)
            latest.setdefault(key, str(r[0]))
        result = []
        seen = set()
        for row in rows:
            key = (row[1], str(row[2]), str(row[3]))
            current = key not in seen
            seen.add(key)
            bound = decode(row[8])
            ids = bound.get("receipt_ids", {})
            supported = (
                current
                and set(ids) == {"audit", "billing", "slo"}
                and str(row[6]) == ids.get("billing")
            )
            for kind, id in ids.items():
                receipt = by_id.get(id)
                if (
                    not receipt
                    or receipt[0] != kind
                    or latest.get(identity(kind, receipt[1])) != id
                ):
                    supported = False
            if supported:
                ledger = evidence.ledger_pair(
                    db, tenant["tenant_id"], case, by_id[str(row[6])][1]
                )
                supported = ledger["digest"] == row[5]
            result.append(
                dict(
                    id=str(row[0]),
                    currency=row[1],
                    period_start=str(row[2]),
                    period_end=str(row[3]),
                    recorded_amount=str(row[4]),
                    revision=row[7],
                    is_current_revision=current,
                    supported=bool(supported),
                    current_supported_amount=str(row[4]) if supported else None,
                )
            )
        return result

    def save_receipt(self, tenant, raw, signature):
        envelope, payload, fingerprint = evidence.validate_receipt(
            raw, signature, tenant, self.clock()
        )
        with self.store.transaction(tenant["tenant_id"], write=True) as db:
            case = self._owned(db, tenant, str(envelope.case_id))
            rid = (
                envelope.resource_id.lower()
                if envelope.provider == "azure"
                else envelope.resource_id
            )
            if (
                case is None
                or case["legacy"]
                or (envelope.provider, envelope.scope_id, rid)
                != (case["provider"], case["scope_id"], case["resource_id"])
            ):
                raise ValueError(
                    "Receipt must bind an owned outcome case and exact resource"
                )
            prior = db.execute(
                "SELECT id,fingerprint FROM savings_evidence_receipts WHERE tenant_id=%s AND source_id=%s AND receipt_key=%s",
                (tenant["tenant_id"], envelope.source_id, str(envelope.receipt_id)),
            ).fetchone()
            if prior:
                if prior[1] != fingerprint:
                    raise OutcomeConflict("Receipt key has conflicting evidence")
                return dict(id=str(prior[0]), cached=True)
            id = str(uuid4())
            db.execute(
                "INSERT INTO savings_evidence_receipts(id,tenant_id,receipt_key,source_id,provider,scope_id,resource_id,kind,fingerprint,payload,issued_at,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    id,
                    tenant["tenant_id"],
                    str(envelope.receipt_id),
                    envelope.source_id,
                    envelope.provider,
                    envelope.scope_id,
                    rid,
                    envelope.kind,
                    fingerprint,
                    db.json(payload),
                    envelope.issued_at.isoformat(),
                    self.clock().isoformat(),
                ),
            )
            return dict(id=id, cached=False)

    def billing_preview(self, tenant, id, body):
        with self.store.transaction(tenant["tenant_id"]) as db:
            case = self._owned(db, tenant, id)
            return (
                evidence.ledger_pair(db, tenant["tenant_id"], case, body)
                if case
                else None
            )

    def act(self, tenant, id, body, scan=None):
        tid = tenant["tenant_id"]
        now = self.clock()
        who = actor(tenant)
        with self.store.transaction(tid, write=True) as db:
            case = self._owned(db, tenant, id)
            if case is None:
                return None
            if case["legacy"]:
                raise OutcomeConflict(
                    "Legacy cases retain their history; create a v2 case for the new lifecycle"
                )
            if case["version"] != body.version:
                raise OutcomeConflict("Case changed. Refresh before updating.")
            p = dict(case["payload"])
            state = case["state"]
            verification = case["verification"]
            proofs = self.receipts(db, tenant, case)
            if body.action == "assign" and state in ("detected", "assigned"):
                if not body.owner:
                    raise ValueError("Choose an accountable owner")
                p.update(owner=body.owner, assigned_at=now.isoformat())
                state = "assigned"
            elif body.action == "review" and state == "assigned":
                p.update(reviewed_by=who, reviewed_at=now.isoformat())
                state = "reviewed"
            elif body.action == "approve" and state == "reviewed":
                if not human(tenant):
                    raise OutcomeConflict(
                        "A verified human TenantAdmin session is required to approve"
                    )
                if not body.change_reference:
                    raise ValueError("Link the approved change reference")
                p.update(
                    approved_by=who,
                    approved_at=now.isoformat(),
                    change_reference=body.change_reference,
                )
                state = "approved"
            elif body.action == "implement" and state == "approved":
                audit = (proofs.get("audit") or {}).get("proof") or {}
                at = evidence.moment(audit.get("occurred_at"))
                if (
                    not at
                    or not evidence.moment(p.get("approved_at")) <= at <= now
                    or audit.get("before_configuration_digest")
                    != p["configuration_digest"]
                    or audit.get("operation")
                    != ("delete" if p["action"] == "retirement" else "resize")
                ):
                    raise OutcomeConflict(
                        "A signed successful provider action matching the saved approval is required"
                    )
                event_key = digest(
                    [
                        case["provider"],
                        case["scope_id"],
                        case["resource_id"],
                        audit["event_id"],
                    ]
                )
                used = db.execute(
                    "SELECT case_id FROM savings_verified_actions WHERE tenant_id=%s AND event_key=%s",
                    (tid, event_key),
                ).fetchone()
                if used and str(used[0]) != id:
                    raise OutcomeConflict(
                        "This provider action is already bound to another case"
                    )
                if not used:
                    db.execute(
                        "INSERT INTO savings_verified_actions(id,tenant_id,case_id,event_key,receipt_id,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                        (
                            str(uuid4()),
                            tid,
                            id,
                            event_key,
                            proofs["audit"]["id"],
                            now.isoformat(),
                        ),
                    )
                p.update(
                    implemented_at=at.isoformat(),
                    audit_receipt_id=proofs["audit"]["id"],
                )
                state = "implemented"
            elif body.action in ("validate", "reconcile") and state in (
                "implemented",
                "validated",
                "financially_reconciled",
            ):
                if scan is None:
                    raise ValueError("Select a completed post-change scan")
                ledger = (
                    evidence.ledger_pair(db, tid, case, proofs["billing"]["proof"])
                    if "billing" in proofs
                    else None
                )
                verification = evidence.evaluate(case, scan, proofs, ledger, now)
                verification.update(
                    receipt_ids={k: v["id"] for k, v in proofs.items()},
                    post_scan_id=scan["scan_id"],
                )
                if body.action == "validate":
                    if state == "financially_reconciled":
                        raise OutcomeConflict(
                            "Use finance reconciliation to revise a reconciled outcome"
                        )
                    state = (
                        "validated"
                        if verification["validated_run_rate_reduction"] is not None
                        else "implemented"
                    )
                    if state == "validated":
                        p["validated_at"] = now.isoformat()
                    # Validation does not itself book a financial benefit.
                    verification["reconciled_financial_benefit"] = None
                else:
                    if state not in ("validated", "financially_reconciled"):
                        raise OutcomeConflict(
                            "Validate the run-rate outcome before financial reconciliation"
                        )
                    if not human(tenant) or who == p.get("approved_by"):
                        raise OutcomeConflict(
                            "A different verified human finance reviewer must reconcile the outcome"
                        )
                    if verification.get("reconciled_financial_benefit") is not None:
                        duplicate = db.execute(
                            "SELECT id FROM savings_financial_claims WHERE tenant_id=%s AND case_id=%s AND receipt_id=%s",
                            (tid, id, proofs["billing"]["id"]),
                        ).fetchone()
                        if (
                            duplicate
                            and state == "financially_reconciled"
                            and verification["receipt_ids"]
                            == (case["verification"] or {}).get("receipt_ids")
                        ):
                            return case
                        if duplicate:
                            raise OutcomeConflict(
                                "Issue a new signed billing receipt before reconciling revised audit or health evidence"
                            )
                        existing = db.execute(
                            "SELECT case_id,period_start,period_end,receipt_id FROM savings_financial_claims WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND resource_id=%s AND currency=%s AND period_start<%s AND period_end>%s",
                            (
                                tid,
                                case["provider"],
                                case["scope_id"],
                                case["resource_id"],
                                p["currency"],
                                verification["period_end"],
                                verification["period_start"],
                            ),
                        ).fetchone()
                        if existing and (
                            str(existing[0]) != id
                            or str(existing[1]) != verification["period_start"]
                            or str(existing[2]) != verification["period_end"]
                        ):
                            raise OutcomeConflict(
                                "This resource billing period overlaps an existing financial claim"
                            )
                        revision = (
                            db.execute(
                                "SELECT max(revision) FROM savings_financial_claims WHERE tenant_id=%s AND case_id=%s AND currency=%s AND period_start=%s AND period_end=%s",
                                (
                                    tid,
                                    id,
                                    p["currency"],
                                    verification["period_start"],
                                    verification["period_end"],
                                ),
                            ).fetchone()[0]
                            or 0
                        )
                        db.execute(
                            "INSERT INTO savings_financial_claims(id,tenant_id,case_id,provider,scope_id,resource_id,currency,period_start,period_end,receipt_id,revision,amount,evidence,ledger_digest,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                str(uuid4()),
                                tid,
                                id,
                                case["provider"],
                                case["scope_id"],
                                case["resource_id"],
                                p["currency"],
                                verification["period_start"],
                                verification["period_end"],
                                proofs["billing"]["id"],
                                revision + 1,
                                verification["reconciled_financial_benefit"],
                                db.json(dict(receipt_ids=verification["receipt_ids"])),
                                verification["ledger_digest"],
                                now.isoformat(),
                            ),
                        )
                        p.update(reconciled_by=who, reconciled_at=now.isoformat())
                        state = "financially_reconciled"
                    else:
                        state = (
                            "validated"
                            if verification.get("validated_run_rate_reduction")
                            is not None
                            else "implemented"
                        )
            elif body.action == "reopen" and state in (
                "implemented",
                "validated",
                "financially_reconciled",
            ):
                p["last_verification"] = verification
                p["reopened_at"] = now.isoformat()
                verification = None
                state = "assigned"
            else:
                raise OutcomeConflict(
                    "This action is not permitted in the current lifecycle stage"
                )
            return self._save(
                db, tenant, case, state, p, verification, body.action, body.note
            )

    def summary(self, tenant):
        values = {}
        implemented = validated = 0
        seen = set()
        for row in self.cases(tenant):
            if row["legacy"]:
                continue
            case = self.detail(tenant, row["id"])
            p = case["payload"]
            v = case["verification"] or {}
            currency = p["currency"]
            bucket = values.setdefault(
                currency,
                dict(
                    estimated=Decimal(0),
                    run_rate=Decimal(0),
                    financial=Decimal(0),
                    estimate_count=0,
                    run_rate_count=0,
                    financial_count=0,
                    unpriced=0,
                    unsupported_financial=0,
                ),
            )
            key = (case["provider"], case["scope_id"], case["resource_id"], currency)
            if key not in seen:
                seen.add(key)
                if p["estimated_opportunity"] is not None:
                    bucket["estimated"] += Decimal(p["estimated_opportunity"])
                    bucket["estimate_count"] += 1
                else:
                    bucket["unpriced"] += 1
                if case["run_rate_evidence_current"]:
                    bucket["run_rate"] += Decimal(v["validated_run_rate_reduction"])
                    bucket["run_rate_count"] += 1
            implemented += bool(p.get("implemented_at"))
            validated += case["run_rate_evidence_current"]
            for claim in case["financial_claims"]:
                if claim["supported"]:
                    bucket["financial"] += Decimal(claim["current_supported_amount"])
                    bucket["financial_count"] += 1
                elif claim["is_current_revision"]:
                    bucket["unsupported_financial"] += 1
        return dict(
            currencies=[
                dict(
                    currency=k,
                    estimated_opportunity=format(v["estimated"], "f")
                    if v["estimate_count"]
                    else None,
                    validated_run_rate_reduction=format(v["run_rate"], "f")
                    if v["run_rate_count"]
                    else None,
                    reconciled_financial_benefit=format(v["financial"], "f")
                    if v["financial_count"]
                    else None,
                    unpriced_cases=v["unpriced"],
                    unsupported_financial_claims=v["unsupported_financial"],
                )
                for k, v in values.items()
            ],
            implemented_cases=implemented,
            validated_cases=validated,
            validated_outcome_pct=round(validated * 100 / implemented, 2)
            if implemented
            else None,
            warning="Estimates and run rates are per 30 days and use the latest case per resource/currency; historical reconciled benefit covers saved, nonoverlapping observation windows. Currencies are never combined. No case action executes infrastructure.",
        )
