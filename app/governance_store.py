"""Separate governance records, explicit delegated authority and hash-linked decisions."""

from datetime import datetime, date, timedelta, timezone
from uuid import UUID, uuid4, uuid5
from app.enterprise_store import decode
from app.focus import digest
from app.principals import actor
from app.outcome_contracts import human
from app.governance_contracts import CONTROL, ROLES
from app import governance_evidence as evidence
from app.telemetry_contract import moment
from app.data_scope import metadata_visible, predicate


class GovernanceConflict(ValueError):
    pass


class GovernanceForbidden(PermissionError):
    pass


MUTABLE = {
    "finding": "gov_findings",
    "risk": "gov_risks",
    "exception": "gov_exceptions",
}


class Governance:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _subject(self, t):
        return str(t.get("subject_id") or t.get("user_id") or "")

    def _grant(self, db, tid, subject, role):
        row = db.execute(
            "SELECT id,version,payload FROM gov_grants WHERE tenant_id=%s AND subject_id=%s AND role=%s ORDER BY version DESC LIMIT 1",
            (tid, subject, role),
        ).fetchone()
        if not row:
            return None
        p = decode(row[2])
        end = moment(p["expires_at"])
        return (
            dict(p, id=str(row[0]), version=row[1])
            if p["active"] and end and end > self.clock()
            else None
        )

    def _roles(self, db, t):
        return {
            role: g
            for role in ROLES
            if (g := self._grant(db, t["tenant_id"], self._subject(t), role))
        }

    def _need(self, db, t, *roles, person=True):
        if person and not human(t):
            raise GovernanceForbidden("A verified human session is required")
        grants = self._roles(db, t)
        for role in roles:
            if role in grants:
                return dict(grants[role], role=role)
        raise GovernanceForbidden(
            "A delegated governance role is required for this decision"
        )

    def _read(self, db, t):
        if not self._roles(db, t) and "TenantAdmin" not in t.get("roles", []):
            raise GovernanceForbidden("Governance access has not been delegated")

    def _admin(self, t):
        if not human(t) or "TenantAdmin" not in t.get("roles", []):
            raise GovernanceForbidden(
                "Verified human TenantAdmin must manage delegated governance access"
            )

    def _policy(self, db, tid):
        row = db.execute(
            "SELECT version,payload,id FROM gov_controls WHERE tenant_id=%s AND control_key=%s ORDER BY version DESC LIMIT 1",
            (tid, CONTROL),
        ).fetchone()
        return (
            dict(decode(row[1]), version=row[0], id=str(row[2]), control_key=CONTROL)
            if row
            else None
        )

    def _get(self, db, t, kind, id):
        row = db.execute(
            "SELECT id,state,version,payload,created_at,updated_at FROM "
            + MUTABLE[kind]
            + " WHERE tenant_id=%s AND id=%s",
            (t["tenant_id"], id),
        ).fetchone()
        if not row:
            return None
        return dict(
            id=str(row[0]),
            state=row[1],
            version=row[2],
            payload=decode(row[3]),
            created_at=str(row[4]),
            updated_at=str(row[5]),
        )

    def _finding_scope_visible(self, db, t, finding_id):
        row = db.execute(
            "SELECT provider,scope_id FROM gov_findings WHERE tenant_id=%s AND id=%s",
            (t["tenant_id"], finding_id),
        ).fetchone()
        if not row:
            return False
        return metadata_visible(t, {"provider": row[0], "scope_id": row[1]})

    def _visible(self, db, t, kind, item):
        if kind == "finding":
            p = item["payload"]
            return metadata_visible(t, {"provider": p.get("provider"), "scope_id": p.get("scope_id")})
        if kind == "exception":
            return self._finding_scope_visible(db, t, item["payload"]["finding_id"])
        if kind == "risk":
            return all(self._finding_scope_visible(db, t, fid) for fid in item["payload"]["finding_ids"])
        return True

    def _required(self, db, t, kind, id):
        value = self._get(db, t, kind, id)
        if value is None or not self._visible(db, t, kind, value):
            raise KeyError("Owned governance record not found")
        return value

    def _event(self, db, t, kind, id, action, data):
        last = db.execute(
            "SELECT version,event_hash FROM gov_events WHERE tenant_id=%s AND entity_type=%s AND entity_id=%s ORDER BY version DESC LIMIT 1",
            (t["tenant_id"], kind, id),
        ).fetchone()
        previous = last[1] if last else "0" * 64
        version = last[0] + 1 if last else 1
        stamp = self.clock().isoformat()
        payload = dict(
            action=action,
            actor=actor(t),
            subject_id=self._subject(t),
            at=stamp,
            data=data,
        )
        hashed = digest(
            dict(
                tenant_id=t["tenant_id"],
                entity_type=kind,
                entity_id=id,
                version=version,
                previous_hash=previous,
                payload=payload,
            )
        )
        db.execute(
            "INSERT INTO gov_events(id,tenant_id,entity_type,entity_id,version,payload,previous_hash,event_hash,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                str(uuid4()),
                t["tenant_id"],
                kind,
                id,
                version,
                db.json(payload),
                previous,
                hashed,
                stamp,
            ),
        )

    def _history(self, db, t, kind, id):
        rows = db.execute(
            "SELECT version,payload,previous_hash,event_hash FROM gov_events WHERE tenant_id=%s AND entity_type=%s AND entity_id=%s ORDER BY version LIMIT 1001",
            (t["tenant_id"], kind, id),
        ).fetchall()
        if len(rows) > 1000:
            raise ValueError("Audit history exceeds the supported export limit")
        result = []
        previous = "0" * 64
        for row in rows:
            payload = decode(row[1])
            value = dict(
                tenant_id=t["tenant_id"],
                entity_type=kind,
                entity_id=id,
                version=row[0],
                previous_hash=row[2],
                payload=payload,
            )
            if (
                row[0] != len(result) + 1
                or row[2] != previous
                or digest(value) != row[3]
            ):
                raise GovernanceConflict(
                    "Governance audit history integrity check failed"
                )
            result.append(
                dict(
                    version=row[0],
                    payload=payload,
                    previous_hash=row[2],
                    event_hash=row[3],
                )
            )
            previous = row[3]
        return result

    def _update(self, db, t, kind, item, state, p, action, note):
        result = db.execute(
            "UPDATE "
            + MUTABLE[kind]
            + " SET state=%s,version=version+1,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=%s",
            (
                state,
                db.json(p),
                self.clock().isoformat(),
                t["tenant_id"],
                item["id"],
                item["version"],
            ),
        )
        if result.rowcount != 1:
            raise GovernanceConflict("Record changed. Refresh before deciding.")
        self._event(
            db,
            t,
            kind,
            item["id"],
            action,
            dict(note=note, before=item["state"], after=state, snapshot=p),
        )
        return self._required(db, t, kind, item["id"])

    def _insert(self, db, t, kind, id, state, p, **columns):
        now = self.clock().isoformat()
        names = [
            "id",
            "tenant_id",
            "state",
            "version",
            "payload",
            "created_at",
            "updated_at",
            *columns,
        ]
        values = [id, t["tenant_id"], state, 1, db.json(p), now, now, *columns.values()]
        db.execute(
            "INSERT INTO "
            + MUTABLE[kind]
            + "("
            + ",".join(names)
            + ") VALUES("
            + ",".join(["%s"] * len(names))
            + ")",
            tuple(values),
        )
        self._event(db, t, kind, id, "created", p)
        return self._required(db, t, kind, id)

    def capabilities(self, t):
        with self.store.transaction(t["tenant_id"]) as db:
            roles = self._roles(db, t)
            return dict(
                roles=list(roles),
                subject_id=self._subject(t),
                human=bool(human(t)),
                manage_access=bool(human(t) and "TenantAdmin" in t.get("roles", [])),
                readable=bool(roles or "TenantAdmin" in t.get("roles", [])),
                control_key=CONTROL,
                automatic_execution=False,
            )

    def grants(self, t):
        self._admin(t)
        with self.store.transaction(t["tenant_id"]) as db:
            rows = db.execute(
                "SELECT subject_id,role,version,payload FROM gov_grants WHERE tenant_id=%s ORDER BY version DESC,created_at DESC LIMIT 1001",
                (t["tenant_id"],),
            ).fetchall()
        if len(rows) > 1000:
            raise ValueError("Governance grant history exceeds pilot limit")
        latest = {}
        for subject, role, version, p in rows:
            latest.setdefault(
                (subject, role),
                dict(decode(p), subject_id=subject, role=role, version=version),
            )
        return list(latest.values())

    def grant(self, t, body):
        self._admin(t)
        p = body.model_dump(mode="json")
        end = moment(p["expires_at"])
        if not end or not self.clock() < end <= self.clock() + timedelta(days=90):
            raise ValueError("Delegation must expire within 90 days")
        with self.store.transaction(t["tenant_id"], write=True) as db:
            last = (
                db.execute(
                    "SELECT max(version) FROM gov_grants WHERE tenant_id=%s AND subject_id=%s AND role=%s",
                    (t["tenant_id"], p["subject_id"], p["role"]),
                ).fetchone()[0]
                or 0
            )
            if last != body.version:
                raise GovernanceConflict("Delegation changed. Refresh first.")
            p["version"] = last + 1
            id = str(uuid4())
            db.execute(
                "INSERT INTO gov_grants(id,tenant_id,subject_id,role,version,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    id,
                    t["tenant_id"],
                    p["subject_id"],
                    p["role"],
                    last + 1,
                    db.json(p),
                    actor(t),
                    self.clock().isoformat(),
                ),
            )
            self._event(
                db,
                t,
                "access",
                p["subject_id"] + ":" + p["role"],
                "delegation_changed",
                p,
            )
            return p

    def directory(self, t):
        with self.store.transaction(t["tenant_id"]) as db:
            self._read(db, t)
            rows = db.execute(
                "SELECT DISTINCT subject_id FROM gov_grants WHERE tenant_id=%s LIMIT 1001",
                (t["tenant_id"],),
            ).fetchall()
            if len(rows) > 1000:
                raise ValueError("Governance directory exceeds pilot bound")
            result = []
            for row in rows:
                grants = [
                    (role, self._grant(db, t["tenant_id"], row[0], role))
                    for role in ROLES
                ]
                active = [(role, g) for role, g in grants if g]
                if active:
                    result.append(
                        dict(
                            subject_id=row[0],
                            alias=active[0][1].get("alias", "delegate"),
                            roles=[role for role, _ in active],
                        )
                    )
            return result

    def policy(self, t):
        with self.store.transaction(t["tenant_id"]) as db:
            self._read(db, t)
            return self._policy(db, t["tenant_id"])

    def save_policy(self, t, body):
        with self.store.transaction(t["tenant_id"], write=True) as db:
            grant = self._need(db, t, "ComplianceReviewer")
            old = self._policy(db, t["tenant_id"])
            if body.version != (old["version"] if old else 0):
                raise GovernanceConflict("Control policy changed")
            if old and old["mandatory_obligation"] and not body.mandatory_obligation:
                raise GovernanceConflict(
                    "A mandatory obligation cannot be downgraded by an application policy revision"
                )
            if not self._grant(
                db, t["tenant_id"], str(body.owner), "ComplianceReviewer"
            ):
                raise ValueError(
                    "Control owner needs an active ComplianceReviewer delegation"
                )
            p = body.model_dump(mode="json")
            p.update(
                control_key=CONTROL,
                title="Production customer-data storage must disallow public blob access",
                assessment_method="Observed Azure account flag and human-reviewed business context",
                technical_check_only=True,
                reviewed_by=self._subject(t),
                authority=grant["id"],
            )
            version = body.version + 1
            db.execute(
                "INSERT INTO gov_controls(id,tenant_id,control_key,version,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    str(uuid4()),
                    t["tenant_id"],
                    CONTROL,
                    version,
                    db.json(p),
                    actor(t),
                    self.clock().isoformat(),
                ),
            )
            self._event(
                db, t, "control", CONTROL, "policy_reviewed", dict(p, version=version)
            )
            return self._policy(db, t["tenant_id"])

    def _save_assessment(self, db, t, finding_id, value):
        value = dict(value, id=str(uuid4()))
        ordinal = (
            db.execute(
                "SELECT max(ordinal) FROM gov_assessments WHERE tenant_id=%s",
                (t["tenant_id"],),
            ).fetchone()[0]
            or 0
        ) + 1
        db.execute(
            "INSERT INTO gov_assessments(id,tenant_id,finding_id,ordinal,payload,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                value["id"],
                t["tenant_id"],
                finding_id,
                ordinal,
                db.json(value),
                self.clock().isoformat(),
            ),
        )
        return value

    def _assessment(self, db, t, finding_id, resource, scan, context, policy):
        return self._save_assessment(
            db,
            t,
            finding_id,
            evidence.evaluate(resource, scan, context, policy, self.clock()),
        )

    def assess(self, t, resource, scan, body):
        with self.store.transaction(t["tenant_id"], write=True) as db:
            self._need(db, t, "SecurityAnalyst")
            policy = self._policy(db, t["tenant_id"])
            if not policy:
                raise GovernanceConflict("A reviewed control policy is required")
            provider = resource.get("cloud_provider", "azure")
            scope = resource.get("scope_id") or resource.get("subscription_id")
            rid = resource["resource_id"].lower()
            if provider != "azure":
                raise ValueError("This control supports Azure only")
            id = str(uuid5(UUID(t["tenant_id"]), CONTROL + ":" + scope + ":" + rid))
            context = body.context.model_dump(mode="json")
            for field, role in [
                ("technical_owner", "ResourceOwner"),
                ("business_owner", "BusinessRiskOwner"),
            ]:
                if not self._grant(db, t["tenant_id"], context[field], role):
                    raise ValueError(
                        "Named owners need current matching governance delegations"
                    )
            assessment = self._assessment(db, t, id, resource, scan, context, policy)
            item = self._get(db, t, "finding", id)
            if not item and assessment["result"] in ("fail", "unknown"):
                count = db.execute(
                    "SELECT count(*) FROM gov_findings WHERE tenant_id=%s",
                    (t["tenant_id"],),
                ).fetchone()[0]
                if count >= 1000:
                    raise ValueError("Governance finding limit reached")
                p = dict(
                    resource_name=resource.get("resource_name", rid),
                    resource_type=resource["resource_type"],
                    provider=provider,
                    scope_id=scope,
                    resource_id=rid,
                    context=context,
                    control=policy,
                    original_assessment=assessment,
                    assessment=assessment,
                    risk_id=None,
                    severity="unassessed",
                    due_date=None,
                    plan=None,
                    approval=None,
                    implementation=None,
                    verification=None,
                )
                item = self._insert(
                    db,
                    t,
                    "finding",
                    id,
                    "triage",
                    p,
                    provider=provider,
                    scope_id=scope,
                    resource_id=rid,
                    control_key=CONTROL,
                )
            elif item:
                p = dict(item["payload"])
                previous = p["assessment"]
                changed = previous["state_digest"] != assessment["state_digest"]
                p.update(assessment=assessment, context=context, control=policy)
                state = item["state"]
                expected_fix = (
                    state in ("approved", "implemented", "verified")
                    and assessment["result"] == "pass"
                    and p.get("plan")
                    and previous["context"] == assessment["context"]
                    and p["plan"]["control_version"] == policy["version"]
                )
                if changed and not expected_fix:
                    if (
                        previous["context"]["business_owner"]
                        != context["business_owner"]
                    ):
                        p.update(risk_id=None, severity="unassessed", due_date=None)
                    if (
                        p.get("implementation")
                        and assessment["configuration"]["allow_blob_public_access"]
                        is not True
                    ):
                        p["verification"] = None
                    else:
                        p.update(
                            plan=None,
                            approval=None,
                            implementation=None,
                            verification=None,
                        )
                    if state != "incident_escalated":
                        state = "reopened"
                elif state in ("closed", "dismissed") and assessment["result"] not in (
                    "pass",
                    "not_applicable",
                ):
                    state = "reopened"
                    p["verification"] = None
                item = self._update(
                    db,
                    t,
                    "finding",
                    item,
                    state,
                    p,
                    "assessment_collected",
                    "Human reviewed business context and saved technical evidence",
                )
            return dict(assessment=assessment, finding=item)

    def list(self, t, kind):
        with self.store.transaction(t["tenant_id"]) as db:
            self._read(db, t)
            table = MUTABLE[kind]
            where = "tenant_id=%s"
            args = [t["tenant_id"]]
            if kind == "finding":
                extra, extra_args = predicate(t, "provider", "scope_id")
                where += extra
                args.extend(extra_args)
            rows = db.execute(
                f"SELECT id FROM {table} WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT 1001",
                tuple(args),
            ).fetchall()
            if len(rows) > 1000:
                raise ValueError("Governance record limit exceeded")
            items = [self._get(db, t, kind, str(r[0])) for r in rows]
            return [item for item in items if item and self._visible(db, t, kind, item)]

    def detail(self, t, kind, id):
        with self.store.transaction(t["tenant_id"]) as db:
            self._read(db, t)
            item = self._required(db, t, kind, id)
            item["events"] = self._history(db, t, kind, id)
            if kind == "finding":
                rows = db.execute(
                    "SELECT id,kind,source_id,created_at FROM gov_receipts WHERE tenant_id=%s AND finding_id=%s ORDER BY ordinal DESC LIMIT 100",
                    (t["tenant_id"], id),
                ).fetchall()
                item["evidence"] = [
                    dict(id=str(r[0]), kind=r[1], source_id=r[2], received_at=str(r[3]))
                    for r in rows
                ]
                item["assessment_fresh"] = evidence.fresh(
                    item["payload"]["assessment"], self.clock()
                )
            return item

    def create_risk(self, t, body):
        p = body.model_dump(mode="json")
        now = self.clock()
        if len(set(p["finding_ids"])) != len(
            p["finding_ids"]
        ) or not now.date() < body.review_date <= now.date() + timedelta(days=90):
            raise ValueError(
                "Choose distinct findings and a risk review date within 90 days"
            )
        p.update(
            inherent_score=body.inherent_likelihood * body.inherent_impact,
            residual_score=body.residual_likelihood * body.residual_impact,
        )
        p["material"] = p["inherent_score"] >= 12
        p["fingerprint"] = digest(p)
        id = str(uuid5(UUID(t["tenant_id"]), "risk:" + p["request_key"]))
        with self.store.transaction(t["tenant_id"], write=True) as db:
            self._need(db, t, "SecurityAnalyst")
            old = self._get(db, t, "risk", id)
            if old:
                if old["payload"]["fingerprint"] != p["fingerprint"]:
                    raise GovernanceConflict("Request key is already used")
                return old
            findings = [self._required(db, t, "finding", id) for id in p["finding_ids"]]
            if any(
                f["payload"]["context"]["business_owner"] != p["business_owner"]
                or f["payload"]["risk_id"]
                or f["state"] not in ("triage", "reopened")
                for f in findings
            ):
                raise GovernanceConflict(
                    "Choose unlinked findings with the same accountable business owner"
                )
            risk = self._insert(db, t, "risk", id, "active", p)
            for f in findings:
                data = dict(
                    f["payload"],
                    risk_id=id,
                    severity="critical"
                    if p["inherent_score"] >= 20
                    else "high"
                    if p["inherent_score"] >= 12
                    else "medium"
                    if p["inherent_score"] >= 6
                    else "low",
                )
                self._update(
                    db,
                    t,
                    "finding",
                    f,
                    f["state"],
                    data,
                    "risk_linked",
                    "Business risk and inherent/residual rationale linked",
                )
            return risk

    def submit_receipt(self, t, raw, signature):
        with self.store.transaction(t["tenant_id"], write=True) as db:
            self._need(
                db,
                t,
                "AutomationIdentity",
                "ResourceOwner",
                "SecurityAnalyst",
                "ComplianceReviewer",
                person=False,
            )
            env_id = str(UUID(raw["finding_id"]))
            f = self._required(db, t, "finding", env_id)
            target = dict(
                id=f["id"],
                **{k: f["payload"][k] for k in ("provider", "scope_id", "resource_id")},
            )
            env, proof, hashed = evidence.receipt(
                raw, signature, t["tenant_id"], target, self.clock()
            )
            old = db.execute(
                "SELECT id,fingerprint FROM gov_receipts WHERE tenant_id=%s AND source_id=%s AND receipt_key=%s",
                (t["tenant_id"], env.source_id, str(env.receipt_id)),
            ).fetchone()
            if old:
                if old[1] != hashed:
                    raise GovernanceConflict(
                        "Receipt key already has different evidence"
                    )
                return dict(id=str(old[0]), cached=True)
            ordinal = (
                db.execute(
                    "SELECT max(ordinal) FROM gov_receipts WHERE tenant_id=%s",
                    (t["tenant_id"],),
                ).fetchone()[0]
                or 0
            ) + 1
            id = str(uuid4())
            db.execute(
                "INSERT INTO gov_receipts(id,tenant_id,finding_id,source_id,receipt_key,kind,ordinal,fingerprint,envelope,signature_hex,payload,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    id,
                    t["tenant_id"],
                    f["id"],
                    env.source_id,
                    str(env.receipt_id),
                    env.kind,
                    ordinal,
                    hashed,
                    db.json(raw),
                    signature,
                    db.json(proof),
                    self.clock().isoformat(),
                ),
            )
            self._event(
                db,
                t,
                "finding",
                f["id"],
                "evidence_received",
                dict(
                    receipt_id=id,
                    source_id=env.source_id,
                    kind=env.kind,
                    envelope_fingerprint=hashed,
                ),
            )
            return dict(id=id, cached=False)

    def _receipt(self, db, t, f, id, kind):
        row = db.execute(
            "SELECT source_id,payload,envelope,signature_hex,fingerprint FROM gov_receipts WHERE tenant_id=%s AND finding_id=%s AND id=%s AND kind=%s",
            (t["tenant_id"], f["id"], id, kind),
        ).fetchone()
        target = dict(
            id=f["id"],
            **{k: f["payload"][k] for k in ("provider", "scope_id", "resource_id")},
        )
        if not row or not evidence.granted(row[0], t["tenant_id"], target, kind):
            raise GovernanceConflict(
                "Required signed evidence is missing or its source grant was revoked"
            )
        # Revalidate stored signed facts without treating old acceptance as a new
        # ingestion. Live POST always requires a freshly issued envelope.
        try:
            envelope, normalized, hashed = evidence.receipt(
                decode(row[2]),
                row[3],
                t["tenant_id"],
                target,
                self.clock(),
                require_recent_issuance=False,
            )
            if (
                envelope.kind != kind
                or envelope.source_id != row[0]
                or hashed != row[4]
                or digest(normalized) != digest(decode(row[1]))
            ):
                raise ValueError("Stored evidence mismatch")
        except (ValueError, KeyError, TypeError):
            raise GovernanceConflict(
                "Evidence integrity or collector authority changed; reviewed reattestation is required"
            ) from None
        proof = decode(row[1])
        params = [t["tenant_id"], f["id"], kind]
        predicate = ""
        if kind in ("implementation", "verification"):
            predicate = (
                " AND payload->>'plan_digest'=%s"
                if db.postgres
                else " AND json_extract(payload,'$.plan_digest')=%s"
            )
            params.append(proof["plan_digest"])
        latest = db.execute(
            "SELECT id FROM gov_receipts WHERE tenant_id=%s AND finding_id=%s AND kind=%s"
            + predicate
            + " ORDER BY ordinal DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        if not latest or str(latest[0]) != id:
            raise GovernanceConflict(
                "New collector evidence supersedes this receipt; review the current evidence"
            )
        return proof

    def _approval(self, db, t, p, *, require_current=True):
        a = p.get("approval")
        policy = self._policy(db, t["tenant_id"])
        grant = (
            self._grant(db, t["tenant_id"], a["subject_id"], "ChangeApprover")
            if a
            else None
        )
        if (
            not a
            or require_current
            and (not grant or grant["id"] != a["grant_id"])
            or not p.get("plan")
            or a["plan_digest"] != p["plan"]["digest"]
            or policy["version"] != p["control"]["version"]
        ):
            raise GovernanceConflict(
                "A current, unchanged approval and delegated authority are required"
            )
        if not require_current:
            historical = db.execute(
                "SELECT payload FROM gov_grants WHERE tenant_id=%s AND id=%s AND role=%s",
                (t["tenant_id"], a["grant_id"], "ChangeApprover"),
            ).fetchone()
            if (
                not historical
                or not decode(historical[0])["active"]
                or moment(decode(historical[0])["expires_at"])
                <= moment(a["approved_at"])
            ):
                raise GovernanceConflict(
                    "Historical approval authority is not supported"
                )
        return a

    def _technical_owner(self, t, p):
        if self._subject(t) != p["context"]["technical_owner"]:
            raise GovernanceForbidden(
                "Only the accountable technical owner can submit this treatment"
            )

    def _observe(self, db, t, f, observation):
        if not observation:
            raise GovernanceConflict("A fresh latest owned observation is required")
        resource, scan = observation
        p = f["payload"]
        policy = self._policy(db, t["tenant_id"])
        if not resource:
            resource = dict(
                resource_type=p["resource_type"],
                cloud_provider=p["provider"],
                scope_id=p["scope_id"],
                resource_id=p["resource_id"],
                evidence={},
            )
        return self._assessment(db, t, f["id"], resource, scan, p["context"], policy)

    def act(self, t, id, body, observation=None):
        with self.store.transaction(t["tenant_id"], write=True) as db:
            f = self._required(db, t, "finding", id)
            if f["version"] != body.version:
                raise GovernanceConflict("Finding changed. Refresh before deciding.")
            p = dict(f["payload"])
            state = f["state"]
            subject = self._subject(t)
            now = self.clock()
            action = body.action
            if state == "incident_escalated" and action not in ("resume", "note"):
                raise GovernanceConflict(
                    "Use the incident-response handoff and record independent clearance before normal treatment"
                )
            if action == "triage":
                self._need(db, t, "SecurityAnalyst")
                if state not in ("triage", "reopened"):
                    raise GovernanceConflict(
                        "This finding has already entered treatment"
                    )
                if not p["risk_id"]:
                    raise GovernanceConflict(
                        "Link a separate business risk assessment first"
                    )
                if p["assessment"]["result"] != "fail":
                    raise GovernanceConflict(
                        "Unknown evidence must be investigated before a deviation is triaged"
                    )
                days = {"critical": 1, "high": 7, "medium": 30, "low": 90}[
                    p["severity"]
                ]
                due = body.due_date or (now + timedelta(days=days)).date()
                if not now.date() <= due <= now.date() + timedelta(days=days):
                    raise ValueError("Due date exceeds the versioned severity policy")
                p["due_date"] = str(due)
                state = "triaged"
            elif action == "propose":
                self._need(db, t, "ResourceOwner")
                self._technical_owner(t, p)
                if (
                    state not in ("triaged", "proposed", "approved", "reopened")
                    or not p["risk_id"]
                    or not p["due_date"]
                    or not body.plan
                ):
                    raise GovernanceConflict(
                        "Triage and a complete change proposal are required"
                    )
                assessed = self._observe(db, t, f, observation)
                if (
                    assessed["result"] != "fail"
                    or assessed["state_digest"] != p["assessment"]["state_digest"]
                ):
                    raise GovernanceConflict(
                        "Latest evidence changed or is unknown; reassess before proposing"
                    )
                proposed = body.plan.model_dump(mode="json")
                for field in ("steps", "dependency_checks", "validation_steps"):
                    if any(not 5 <= len(v) <= 500 for v in proposed[field]):
                        raise ValueError("Plan steps must be 5–500 characters")
                if proposed["agent_task_id"]:
                    row = db.execute(
                        "SELECT provider,scope_id,resource_id FROM agent_tasks WHERE tenant_id=%s AND id=%s",
                        (t["tenant_id"], proposed["agent_task_id"]),
                    ).fetchone()
                    if (
                        not row
                        or row[0] != p["provider"]
                        or row[1] != p["scope_id"]
                        or str(row[2]).lower() != p["resource_id"]
                    ):
                        raise ValueError(
                            "Related agent task must bind the same owned resource"
                        )
                if proposed["gitops_request_id"]:
                    row = db.execute(
                        "SELECT scan_id FROM gitops_requests WHERE tenant_id=%s AND id=%s",
                        (t["tenant_id"], proposed["gitops_request_id"]),
                    ).fetchone()
                    if not row or str(row[0]) != p["assessment"]["scan_id"]:
                        raise ValueError(
                            "Related GitOps request must bind this owned baseline scan"
                        )
                proposed.update(
                    resource_id=p["resource_id"],
                    provider=p["provider"],
                    scope_id=p["scope_id"],
                    desired_configuration={"allow_blob_public_access": False},
                    baseline_state_digest=p["assessment"]["state_digest"],
                    control_version=p["control"]["version"],
                    proposed_by=subject,
                    automatic_execution=False,
                    link_semantics="context_only_no_execution_permission",
                )
                proposed["digest"] = digest(proposed)
                p.update(
                    plan=proposed, approval=None, implementation=None, verification=None
                )
                state = "proposed"
            elif action == "approve":
                grant = self._need(db, t, "ChangeApprover")
                if (
                    state != "proposed"
                    or not p["plan"]
                    or subject == p["plan"]["proposed_by"]
                ):
                    raise GovernanceConflict(
                        "A different change approver must review the exact proposed plan"
                    )
                assessed = self._observe(db, t, f, observation)
                if (
                    assessed["result"] != "fail"
                    or assessed["state_digest"] != p["plan"]["baseline_state_digest"]
                    or p["plan"]["control_version"]
                    != self._policy(db, t["tenant_id"])["version"]
                ):
                    raise GovernanceConflict(
                        "Plan or latest control evidence changed; propose and review again"
                    )
                p["approval"] = dict(
                    subject_id=subject,
                    grant_id=grant["id"],
                    plan_digest=p["plan"]["digest"],
                    approved_at=now.isoformat(),
                    expires_at=(now + timedelta(hours=24)).isoformat(),
                )
                state = "approved"
            elif action == "implement":
                self._need(db, t, "ResourceOwner")
                self._technical_owner(t, p)
                if (
                    state not in ("approved", "implemented", "verified", "reopened")
                    or not body.receipt_id
                    or not p.get("plan")
                    or state != "approved"
                    and not p.get("implementation")
                ):
                    raise GovernanceConflict(
                        "An approved plan and signed successful provider event are required"
                    )
                a = self._approval(
                    db, t, p, require_current=not bool(p.get("implementation"))
                )
                proof = self._receipt(db, t, f, str(body.receipt_id), "implementation")
                at = moment(proof["occurred_at"])
                if proof["plan_digest"] != p["plan"]["digest"] or not moment(
                    a["approved_at"]
                ) <= at <= min(now, moment(a["expires_at"])):
                    raise GovernanceConflict(
                        "Provider event is outside the exact plan approval"
                    )
                if p.get("implementation") and (
                    proof["event_id"] != p["implementation"]["event_id"]
                    or at != moment(p["implementation"]["occurred_at"])
                ):
                    raise GovernanceConflict(
                        "Reattestation may only replace evidence for the same already-authorized provider event"
                    )
                eventkey = digest(
                    [p["provider"], p["scope_id"], p["resource_id"], proof["event_id"]]
                )
                used = db.execute(
                    "SELECT finding_id FROM gov_actions WHERE tenant_id=%s AND event_key=%s",
                    (t["tenant_id"], eventkey),
                ).fetchone()
                if used and str(used[0]) != id:
                    raise GovernanceConflict(
                        "Provider event already implements another finding"
                    )
                if not used:
                    db.execute(
                        "INSERT INTO gov_actions(id,tenant_id,finding_id,event_key,payload,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                        (
                            str(uuid4()),
                            t["tenant_id"],
                            id,
                            eventkey,
                            db.json(dict(receipt_id=str(body.receipt_id))),
                            now.isoformat(),
                        ),
                    )
                p["implementation"] = dict(
                    subject_id=(p.get("implementation") or {}).get(
                        "subject_id", subject
                    ),
                    receipt_id=str(body.receipt_id),
                    occurred_at=at.isoformat(),
                    event_id=proof["event_id"],
                )
                p["verification"] = None
                state = "implemented"
            elif action == "verify":
                self._need(db, t, "ComplianceReviewer")
                if (
                    state not in ("implemented", "verified", "reopened")
                    or not p["implementation"]
                    or not body.receipt_id
                ):
                    raise GovernanceConflict(
                        "Record implementation and signed application-access verification before independent review"
                    )
                if not p.get("risk_id"):
                    raise GovernanceConflict(
                        "Review the current business risk context before verification or closure"
                    )
                self._approval(db, t, p, require_current=False)
                if subject in {
                    p["plan"]["proposed_by"],
                    p["approval"]["subject_id"],
                    p["implementation"]["subject_id"],
                }:
                    raise GovernanceConflict(
                        "Independent verifier must differ from proposer, implementer and change approver"
                    )
                self._receipt(
                    db, t, f, p["implementation"]["receipt_id"], "implementation"
                )
                assessed = self._observe(db, t, f, observation)
                proof = self._receipt(db, t, f, str(body.receipt_id), "verification")
                observed = moment(assessed["observed_at"])
                checked = moment(proof["observed_at"])
                if (
                    assessed["result"] != "pass"
                    or not proof["health_accepted"]
                    or not proof["legitimate_access_accepted"]
                    or proof["plan_digest"] != p["plan"]["digest"]
                    or proof["scan_id"] != assessed["scan_id"]
                    or proof["state_digest"] != assessed["state_digest"]
                    or not moment(p["implementation"]["occurred_at"])
                    < observed
                    <= checked
                    <= now
                    or now - checked > timedelta(hours=1)
                ):
                    raise GovernanceConflict(
                        "Fresh passing configuration and accepted legitimate application access must match the exact implemented plan"
                    )
                p.update(
                    assessment=assessed,
                    verification=dict(
                        subject_id=subject,
                        verified_at=now.isoformat(),
                        assessment=assessed,
                        receipt_id=str(body.receipt_id),
                    ),
                )
                state = "verified"
            elif action == "close":
                self._need(db, t, "SecurityAnalyst", "ComplianceReviewer")
                if (
                    state != "verified"
                    or not p["verification"]
                    or subject
                    in {
                        p["plan"]["proposed_by"],
                        p["approval"]["subject_id"],
                        p["implementation"]["subject_id"],
                    }
                ):
                    raise GovernanceConflict(
                        "A non-executing control reviewer must approve independent verification"
                    )
                if not p.get("risk_id"):
                    raise GovernanceConflict(
                        "Review the current business risk context before verification or closure"
                    )
                self._approval(db, t, p, require_current=False)
                self._receipt(
                    db, t, f, p["implementation"]["receipt_id"], "implementation"
                )
                self._receipt(db, t, f, p["verification"]["receipt_id"], "verification")
                assessed = self._observe(db, t, f, observation)
                if (
                    assessed["result"] != "pass"
                    or assessed["state_digest"]
                    != p["verification"]["assessment"]["state_digest"]
                    or not now - moment(p["verification"]["verified_at"])
                    <= timedelta(hours=24)
                ):
                    raise GovernanceConflict(
                        "Verification or current configuration is stale or changed"
                    )
                p.update(
                    assessment=assessed,
                    closed_at=now.isoformat(),
                    closed_by=subject,
                    closure_claim="Verified configuration and legitimate access only; no claim of no historical data exposure or organizational compliance",
                )
                state = "closed"
            elif action == "request_dismissal":
                self._need(db, t, "ResourceOwner")
                self._technical_owner(t, p)
                if state in ("closed", "accepted_risk", "exception_scheduled"):
                    raise GovernanceConflict(
                        "This treatment has a different review path"
                    )
                if not body.dismissal_kind:
                    raise ValueError(
                        "A documented dismissal classification is required"
                    )
                p["dismissal"] = dict(
                    kind=body.dismissal_kind, requested_by=subject, rationale=body.note
                )
                state = "dismissal_review"
            elif action == "dismiss":
                self._need(db, t, "SecurityAnalyst")
                if (
                    state != "dismissal_review"
                    or subject == p["dismissal"]["requested_by"]
                ):
                    raise GovernanceConflict("Independent analyst review is required")
                assessed = self._observe(db, t, f, observation)
                expected = (
                    "not_applicable"
                    if p["dismissal"]["kind"] == "not_applicable"
                    else "pass"
                )
                if assessed["result"] != expected:
                    raise GovernanceConflict(
                        "Fresh corrected evidence/context is required; unknown or failing controls cannot be dismissed by assertion"
                    )
                if p["dismissal"]["kind"] == "false_positive":
                    if not body.receipt_id:
                        raise GovernanceConflict(
                            "A passing new configuration does not refute the original finding; signed source correction is required"
                        )
                    proof = self._receipt(db, t, f, str(body.receipt_id), "correction")
                    if (
                        not proof["false_positive_supported"]
                        or proof["original_scan_id"]
                        != p["original_assessment"]["scan_id"]
                        or proof["original_state_digest"]
                        != p["original_assessment"]["state_digest"]
                        or not now - timedelta(hours=24)
                        <= moment(proof["evaluated_at"])
                        <= now
                    ):
                        raise GovernanceConflict(
                            "Current source correction must explicitly refute the frozen original observation"
                        )
                    p["dismissal"] = dict(
                        p["dismissal"], correction_receipt_id=str(body.receipt_id)
                    )
                p.update(assessment=assessed, dismissed_at=now.isoformat())
                state = "dismissed"
            elif action == "incident":
                self._need(db, t, "SecurityAnalyst")
                if not body.incident_reference:
                    raise ValueError("Link the incident-response handoff reference")
                p["incident"] = dict(
                    reference=body.incident_reference,
                    escalated_by=subject,
                    at=now.isoformat(),
                    reason=body.note,
                    clearance=None,
                )
                p["verification"] = None
                state = "incident_escalated"
            elif action == "resume":
                self._need(db, t, "SecurityAnalyst")
                if (
                    state != "incident_escalated"
                    or subject == p["incident"]["escalated_by"]
                ):
                    raise GovernanceConflict(
                        "An independent analyst must record incident-response clearance"
                    )
                if not body.incident_reference:
                    raise ValueError(
                        "A clearance reference from incident response is required"
                    )
                p["incident"] = dict(
                    p["incident"],
                    clearance=dict(
                        subject_id=subject,
                        reference=body.incident_reference,
                        note=body.note,
                        at=now.isoformat(),
                    ),
                )
                p.update(
                    plan=None, approval=None, implementation=None, verification=None
                )
                state = "reopened"
            elif action == "note":
                self._need(
                    db,
                    t,
                    "ResourceOwner",
                    "SecurityAnalyst",
                    "ComplianceReviewer",
                    "BusinessRiskOwner",
                    "ChangeApprover",
                )
            return self._update(db, t, "finding", f, state, p, action, body.note)

    def request_exception(self, t, body):
        p = body.model_dump(mode="json")
        p["fingerprint"] = digest(p)
        id = str(uuid5(UUID(t["tenant_id"]), "exception:" + p["request_key"]))
        now = self.clock()
        with self.store.transaction(t["tenant_id"], write=True) as db:
            self._need(db, t, "ResourceOwner")
            f = self._required(db, t, "finding", p["finding_id"])
            fp = f["payload"]
            self._technical_owner(t, fp)
            old = self._get(db, t, "exception", id)
            if old:
                if old["payload"]["fingerprint"] != p["fingerprint"]:
                    raise GovernanceConflict("Exception request key is already used")
                return old
            policy = self._policy(db, t["tenant_id"])
            risk = (
                self._required(db, t, "risk", fp["risk_id"]) if fp["risk_id"] else None
            )
            if (
                f["state"] not in ("triaged", "reopened")
                or not risk
                or policy["mandatory_obligation"]
                or fp["assessment"]["result"] != "fail"
            ):
                raise GovernanceConflict(
                    "Only a triaged discretionary failing control can request risk acceptance; mandatory obligations cannot be overridden"
                )
            start, end, review = (
                moment(body.start),
                moment(body.end),
                moment(body.review_at),
            )
            if (
                not all((start, end, review))
                or not now
                <= start
                < end
                <= now + timedelta(days=policy["maximum_exception_days"])
                or not start <= review < end
            ):
                raise ValueError(
                    "Exception dates exceed the reviewed policy or lack an earlier review"
                )
            proof = self._receipt(
                db, t, f, str(body.compensation_receipt_id), "compensation"
            )
            if (
                not proof["accepted"]
                or not now - timedelta(hours=24) <= moment(proof["observed_at"]) <= now
                or moment(proof["valid_until"]) < end
            ):
                raise GovernanceConflict(
                    "Accepted, current compensating-control evidence must cover the full exception"
                )
            p.update(
                requested_by=self._subject(t),
                risk_id=risk["id"],
                risk_version=risk["version"],
                control_version=policy["version"],
                state_digest=fp["assessment"]["state_digest"],
                review=None,
                approval=None,
            )
            return self._insert(
                db, t, "exception", id, "requested", p, finding_id=f["id"]
            )

    def decide_exception(self, t, id, body):
        with self.store.transaction(t["tenant_id"], write=True) as db:
            item = self._required(db, t, "exception", id)
            p = dict(item["payload"])
            state = item["state"]
            now = self.clock()
            subject = self._subject(t)
            if body.version != item["version"]:
                raise GovernanceConflict("Exception changed. Refresh first.")
            f = self._required(db, t, "finding", p["finding_id"])
            fp = f["payload"]
            risk = self._required(db, t, "risk", p["risk_id"])
            policy = self._policy(db, t["tenant_id"])
            if body.action == "review":
                grant = self._need(db, t, "SecurityAnalyst")
                if state != "requested" or subject in {
                    p["requested_by"],
                    risk["payload"]["business_owner"],
                }:
                    raise GovernanceConflict(
                        "A separate security analyst must assess compensating controls and residual risk"
                    )
                p["review"] = dict(
                    subject_id=subject,
                    grant_id=grant["id"],
                    at=now.isoformat(),
                    note=body.note,
                    residual_score=risk["payload"]["residual_score"],
                )
                state = "reviewed"
            elif body.action == "approve":
                grant = self._need(db, t, "BusinessRiskOwner")
                if (
                    state != "reviewed"
                    or subject != risk["payload"]["business_owner"]
                    or subject
                    in {
                        p["requested_by"],
                        p["review"]["subject_id"],
                        fp["context"]["technical_owner"],
                    }
                ):
                    raise GovernanceConflict(
                        "The independent accountable business owner must authorize residual risk"
                    )
                if f["state"] not in ("triaged", "reopened") or fp.get("exception_id"):
                    raise GovernanceConflict(
                        "A different accepted treatment already owns this finding"
                    )
                if (
                    date.fromisoformat(risk["payload"]["review_date"])
                    < moment(p["end"]).date()
                ):
                    raise GovernanceConflict(
                        "Risk review must cover the full exception window"
                    )
                reviewer = self._grant(
                    db, t["tenant_id"], p["review"]["subject_id"], "SecurityAnalyst"
                )
                if (
                    not reviewer
                    or reviewer["id"] != p["review"]["grant_id"]
                    or policy["mandatory_obligation"]
                    or policy["version"] != p["control_version"]
                    or risk["version"] != p["risk_version"]
                    or risk["payload"]["inherent_score"] > grant["maximum_score"]
                    or risk["payload"]["residual_score"] > policy["risk_appetite"]
                    or moment(p["end"]) - moment(p["start"])
                    > timedelta(days=grant["maximum_exception_days"])
                    or not now < moment(p["end"])
                    or fp["assessment"]["state_digest"] != p["state_digest"]
                    or not evidence.fresh(fp["assessment"], now)
                ):
                    raise GovernanceConflict(
                        "Authority, policy, residual risk, evidence or exception dates no longer support acceptance"
                    )
                proof = self._receipt(
                    db, t, f, p["compensation_receipt_id"], "compensation"
                )
                if not proof["accepted"] or moment(proof["valid_until"]) < moment(
                    p["end"]
                ):
                    raise GovernanceConflict(
                        "Compensating evidence no longer covers the exception"
                    )
                p["approval"] = dict(
                    subject_id=subject,
                    grant_id=grant["id"],
                    at=now.isoformat(),
                    authority_reference=grant["authority_reference"],
                    note=body.note,
                )
                state = "approved"
                self._update(
                    db,
                    t,
                    "finding",
                    f,
                    "accepted_risk"
                    if moment(p["start"]) <= now
                    else "exception_scheduled",
                    dict(fp, exception_id=id, verification=None),
                    "risk_accepted",
                    "Time-limited risk acceptance; underlying control remains failed",
                )
            elif body.action in ("reject", "revoke"):
                self._need(db, t, "SecurityAnalyst", "BusinessRiskOwner")
                if state not in ("requested", "reviewed", "approved"):
                    raise GovernanceConflict("This exception is already terminal")
                state = "rejected" if body.action == "reject" else "revoked"
                if fp.get("exception_id") == id:
                    self._update(
                        db,
                        t,
                        "finding",
                        f,
                        "reopened",
                        dict(fp, exception_id=None),
                        "exception_revoked",
                        body.note,
                    )
            else:
                raise GovernanceConflict("Unsupported exception decision")
            return self._update(
                db, t, "exception", item, state, p, body.action, body.note
            )

    def decide_risk(self, t, id, body):
        with self.store.transaction(t["tenant_id"], write=True) as db:
            grant = self._need(db, t, "BusinessRiskOwner")
            risk = self._required(db, t, "risk", id)
            p = dict(risk["payload"])
            if risk["version"] != body.version:
                raise GovernanceConflict("Risk changed")
            if (
                self._subject(t) != p["business_owner"]
                or grant["maximum_score"] < p["inherent_score"]
            ):
                raise GovernanceForbidden(
                    "Risk review requires the accountable owner within delegated authority"
                )
            state = risk["state"]
            if body.action == "retire":
                findings = [
                    self._required(db, t, "finding", id) for id in p["finding_ids"]
                ]
                if any(
                    f["state"] not in ("closed", "dismissed")
                    or not evidence.fresh(f["payload"]["assessment"], self.clock())
                    for f in findings
                ):
                    raise GovernanceConflict(
                        "Open, accepted or stale findings prevent risk retirement"
                    )
                state = "retired"
            elif body.action == "review":
                p.update(
                    review_date=str((self.clock() + timedelta(days=30)).date()),
                    reviewed_at=self.clock().isoformat(),
                )
            else:
                raise GovernanceConflict("Risk supports explicit review or retirement")
            return self._update(db, t, "risk", risk, state, p, body.action, body.note)

    def monitor(self, t, observations, *, system=False):
        """Reassess saved observations only. No provider calls, approvals or execution."""
        with self.store.transaction(t["tenant_id"], write=True) as db:
            if not system:
                self._need(db, t, "SecurityAnalyst")
            now = self.clock()
            rows = db.execute(
                "SELECT id FROM gov_findings WHERE tenant_id=%s ORDER BY id LIMIT 1001",
                (t["tenant_id"],),
            ).fetchall()
            if len(rows) > 1000:
                raise ValueError("Governance monitor finding limit exceeded")
            changed = 0
            policy = self._policy(db, t["tenant_id"])
            for row in rows:
                f = self._required(db, t, "finding", str(row[0]))
                p = dict(f["payload"])
                state = f["state"]
                observation = observations.get(f["id"])
                reason = None
                if observation:
                    resource, scan = observation
                    resource = resource or dict(
                        resource_type=p["resource_type"],
                        cloud_provider=p["provider"],
                        scope_id=p["scope_id"],
                        resource_id=p["resource_id"],
                        evidence={},
                    )
                    assessed = evidence.evaluate(
                        resource, scan, p["context"], policy, now
                    )
                else:
                    assessed = dict(
                        p["assessment"],
                        result="unknown",
                        reason="LATEST_OWNED_OBSERVATION_UNAVAILABLE",
                    )
                previous = p["assessment"]
                delta = previous["state_digest"] != assessed["state_digest"]
                needs_assessment = (
                    previous.get("scan_id") != assessed.get("scan_id")
                    or previous["result"] != assessed["result"]
                    or delta
                )
                if needs_assessment:
                    assessed = self._save_assessment(db, t, f["id"], assessed)
                    p["assessment"] = assessed
                if p["control"]["version"] != policy["version"]:
                    p.update(control=policy, verification=None)
                    if not p.get("implementation"):
                        p.update(plan=None, approval=None)
                    reason = "CONTROL_POLICY_CHANGED"
                expected_fix = (
                    state in ("approved", "implemented", "verified")
                    and assessed["result"] == "pass"
                    and p.get("plan")
                    and p["control"]["version"] == policy["version"]
                )
                if delta and not expected_fix:
                    if (
                        p.get("implementation")
                        and assessed["configuration"]["allow_blob_public_access"]
                        is not True
                    ):
                        p["verification"] = None
                    else:
                        p.update(
                            plan=None,
                            approval=None,
                            implementation=None,
                            verification=None,
                        )
                    reason = "CONFIGURATION_OR_CONTEXT_DRIFT"
                elif state in ("closed", "dismissed"):
                    if assessed["result"] not in (
                        "pass",
                        "not_applicable",
                    ) or not evidence.fresh(assessed, now):
                        reason = "EVIDENCE_STALE_OR_FAILED"
                    if state == "closed" and not reason:
                        try:
                            if not p["verification"] or now - moment(
                                p["verification"]["verified_at"]
                            ) > timedelta(hours=24):
                                raise GovernanceConflict("Verification expired")
                            self._receipt(
                                db,
                                t,
                                f,
                                p["implementation"]["receipt_id"],
                                "implementation",
                            )
                            self._receipt(
                                db,
                                t,
                                f,
                                p["verification"]["receipt_id"],
                                "verification",
                            )
                        except GovernanceConflict:
                            reason = "VERIFICATION_OR_COLLECTOR_AUTHORITY_CHANGED"
                    if (
                        state == "dismissed"
                        and p.get("dismissal", {}).get("kind") == "false_positive"
                    ):
                        try:
                            self._receipt(
                                db,
                                t,
                                f,
                                p["dismissal"]["correction_receipt_id"],
                                "correction",
                            )
                        except GovernanceConflict:
                            reason = "SOURCE_CORRECTION_REVOKED_OR_CHANGED"
                elif state in ("approved", "implemented", "verified"):
                    try:
                        a = self._approval(
                            db, t, p, require_current=state == "approved"
                        )
                        if state == "approved" and now > moment(a["expires_at"]):
                            reason = "CHANGE_APPROVAL_EXPIRED"
                    except GovernanceConflict:
                        reason = "CHANGE_AUTHORITY_OR_POLICY_CHANGED"
                if reason and state != "incident_escalated":
                    state = "reopened"
                    p["verification"] = None
                    p["reopen_reason"] = reason
                if (
                    needs_assessment
                    or reason
                    and (
                        state != f["state"]
                        or p.get("reopen_reason") != f["payload"].get("reopen_reason")
                    )
                ):
                    f = self._update(
                        db,
                        t,
                        "finding",
                        f,
                        state,
                        p,
                        "continuous_monitoring",
                        reason or "Latest saved technical evidence reassessed",
                    )
                    changed += 1
                    if state == "reopened" and p.get("risk_id"):
                        risk = self._required(db, t, "risk", p["risk_id"])
                        if risk["state"] == "retired":
                            self._update(
                                db,
                                t,
                                "risk",
                                risk,
                                "active",
                                risk["payload"],
                                "finding_reopened",
                                "Drift reopened a linked retired business risk",
                            )
            exceptions = db.execute(
                "SELECT id FROM gov_exceptions WHERE tenant_id=%s AND state='approved' ORDER BY id LIMIT 1001",
                (t["tenant_id"],),
            ).fetchall()
            if len(exceptions) > 1000:
                raise ValueError("Exception monitor limit exceeded")
            for row in exceptions:
                item = self._required(db, t, "exception", str(row[0]))
                p = dict(item["payload"])
                f = self._required(db, t, "finding", p["finding_id"])
                fp = dict(f["payload"])
                risk = self._required(db, t, "risk", p["risk_id"])
                a = p["approval"]
                authority = self._grant(
                    db, t["tenant_id"], a["subject_id"], "BusinessRiskOwner"
                )
                reason = None
                if now >= moment(p["end"]):
                    reason = "EXCEPTION_EXPIRED"
                elif not authority or authority["id"] != a["grant_id"]:
                    reason = "RISK_ACCEPTANCE_AUTHORITY_REVOKED"
                elif (
                    policy["version"] != p["control_version"]
                    or risk["version"] != p["risk_version"]
                    or date.fromisoformat(risk["payload"]["review_date"]) <= now.date()
                ):
                    reason = "RISK_OR_POLICY_REVIEW_REQUIRED"
                elif (
                    fp["assessment"]["state_digest"] != p["state_digest"]
                    or not evidence.fresh(fp["assessment"], now)
                    or fp["assessment"]["result"] != "fail"
                ):
                    reason = "EXCEPTION_SCOPE_OR_EVIDENCE_CHANGED"
                else:
                    try:
                        proof = self._receipt(
                            db, t, f, p["compensation_receipt_id"], "compensation"
                        )
                        if not proof["accepted"] or moment(
                            proof["valid_until"]
                        ) < moment(p["end"]):
                            raise GovernanceConflict("Compensation expired")
                    except GovernanceConflict:
                        reason = "COMPENSATING_EVIDENCE_REVOKED_OR_CHANGED"
                if reason:
                    self._update(
                        db,
                        t,
                        "exception",
                        item,
                        "expired"
                        if reason == "EXCEPTION_EXPIRED"
                        else "review_required",
                        p,
                        "monitoring_invalidated",
                        reason,
                    )
                    if fp.get("exception_id") == item["id"]:
                        fp["exception_id"] = None
                        self._update(
                            db,
                            t,
                            "finding",
                            f,
                            f["state"]
                            if f["state"] == "incident_escalated"
                            else "reopened",
                            fp,
                            "exception_escalated",
                            reason,
                        )
                    changed += 1
                elif now >= moment(p["start"]) and f["state"] == "exception_scheduled":
                    self._update(
                        db,
                        t,
                        "finding",
                        f,
                        "accepted_risk",
                        fp,
                        "exception_started",
                        "Authorized exception is active; technical control remains failed",
                    )
                if (
                    not reason
                    and moment(p["review_at"]) <= now + timedelta(days=7)
                    and p.get("reminded_on") != str(now.date())
                ):
                    p["reminded_on"] = str(now.date())
                    self._update(
                        db,
                        t,
                        "exception",
                        item,
                        item["state"],
                        p,
                        "review_reminder",
                        "Review is due or approaching; dashboard reminder only",
                    )
            status = dict(
                checked_at=now.isoformat(),
                findings_checked=len(rows),
                changed=changed,
                external_notifications_sent=0,
                automatic_execution=False,
            )
            db.execute(
                "INSERT INTO gov_monitor(tenant_id,payload,updated_at) VALUES(%s,%s,%s) ON CONFLICT(tenant_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (t["tenant_id"], db.json(status), now.isoformat()),
            )
            return status

    def summary(self, t):
        findings = self.list(t, "finding")
        exceptions = self.list(t, "exception")
        risks = self.list(t, "risk")
        now = self.clock()
        with self.store.transaction(t["tenant_id"]) as db:
            rows = db.execute(
                "SELECT payload FROM gov_assessments WHERE tenant_id=%s ORDER BY ordinal DESC LIMIT 5001",
                (t["tenant_id"],),
            ).fetchall()
            monitor = db.execute(
                "SELECT payload FROM gov_monitor WHERE tenant_id=%s", (t["tenant_id"],)
            ).fetchone()
        if len(rows) > 5000:
            raise ValueError("Assessment reporting limit exceeded")
        latest = {}
        for row in rows:
            a = decode(row[0])
            target = a.get("target") or {}
            if not metadata_visible(
                t, {"provider": target.get("provider"), "scope_id": target.get("scope_id")}
            ):
                continue
            latest.setdefault(
                tuple(target.get(k) for k in ("provider", "scope_id", "resource_id")),
                a,
            )
        for f in findings:
            a = f["payload"]["assessment"]
            latest[
                tuple(
                    a["target"].get(k) for k in ("provider", "scope_id", "resource_id")
                )
            ] = a
        assessments = list(latest.values())
        results = {
            k: sum(a["result"] == k and evidence.fresh(a, now) for a in assessments)
            for k in ("pass", "fail", "unknown", "not_applicable")
        }
        stale = sum(not evidence.fresh(a, now) for a in assessments)
        return dict(
            open_material_risks=sum(
                r["state"] != "retired" and r["payload"]["material"] for r in risks
            ),
            overdue_findings=sum(
                f["state"] not in ("closed", "dismissed")
                and f["payload"].get("due_date") is not None
                and date.fromisoformat(f["payload"]["due_date"]) < now.date()
                for f in findings
            ),
            expiring_exceptions=sum(
                e["state"] == "approved"
                and now < moment(e["payload"]["end"]) <= now + timedelta(days=7)
                for e in exceptions
            ),
            unknown_assessments=results["unknown"] + stale,
            stale_evidence=stale,
            unassigned_resources=sum(
                not f["payload"]["context"].get("technical_owner") for f in findings
            ),
            assessment_results=results,
            monitor=decode(monitor[0]) if monitor else None,
            reminders="Dashboard only; no external notifications",
            assessed_resources=len(assessments),
            unassessed_resource_coverage=None,
            compliance_score=None,
            warning="Technical assessment coverage and accepted risks do not establish organizational compliance. Public access configuration cannot prove whether data was previously exposed.",
        )

    def _current_support(self, db, t, f, observation):
        p = f["payload"]
        if f["state"] != "closed" or not p.get("verification") or not observation:
            return False
        resource, scan = observation
        if not resource or not self.clock() - moment(
            p["verification"]["verified_at"]
        ) <= timedelta(hours=24):
            return False
        current = evidence.evaluate(
            resource, scan, p["context"], self._policy(db, t["tenant_id"]), self.clock()
        )
        if (
            current["result"] != "pass"
            or current["state_digest"]
            != p["verification"]["assessment"]["state_digest"]
        ):
            return False
        try:
            self._receipt(db, t, f, p["implementation"]["receipt_id"], "implementation")
            self._receipt(db, t, f, p["verification"]["receipt_id"], "verification")
        except GovernanceConflict:
            return False
        return True

    def export(self, t, id, observation=None):
        with self.store.transaction(t["tenant_id"]) as db:
            self._read(db, t)
            f = self._required(db, t, "finding", id)
            assessments = db.execute(
                "SELECT payload FROM gov_assessments WHERE tenant_id=%s AND finding_id=%s ORDER BY ordinal LIMIT 1001",
                (t["tenant_id"], id),
            ).fetchall()
            receipts = db.execute(
                "SELECT id,source_id,kind,payload,created_at,envelope,signature_hex,fingerprint FROM gov_receipts WHERE tenant_id=%s AND finding_id=%s ORDER BY ordinal LIMIT 1001",
                (t["tenant_id"], id),
            ).fetchall()
            if max(len(assessments), len(receipts)) > 1000:
                raise ValueError("Audit package exceeds supported limit")
            content = dict(
                finding=f,
                finding_history=self._history(db, t, "finding", id),
                assessments=[decode(r[0]) for r in assessments],
                evidence=[
                    dict(
                        id=str(r[0]),
                        source_id=r[1],
                        kind=r[2],
                        proof=decode(r[3]),
                        received_at=str(r[4]),
                        envelope=decode(r[5]),
                        signature_hex=r[6],
                        envelope_fingerprint=r[7],
                    )
                    for r in receipts
                ],
            )
            p = f["payload"]
            if p.get("risk_id"):
                content["risk"] = self._required(db, t, "risk", p["risk_id"])
                content["risk_history"] = self._history(db, t, "risk", p["risk_id"])
            rows = db.execute(
                "SELECT id FROM gov_exceptions WHERE tenant_id=%s AND finding_id=%s ORDER BY created_at,id LIMIT 101",
                (t["tenant_id"], id),
            ).fetchall()
            if len(rows) > 100:
                raise ValueError("Exception audit history exceeds supported limit")
            content["exceptions"] = [
                dict(
                    record=self._required(db, t, "exception", str(r[0])),
                    history=self._history(db, t, "exception", str(r[0])),
                )
                for r in rows
            ]
            content["control_history"] = self._history(db, t, "control", CONTROL)
            actor_ids = {e["payload"]["subject_id"] for e in content["finding_history"]}
            actor_ids.update(
                e["payload"]["subject_id"] for e in content.get("risk_history", [])
            )
            for exception in content["exceptions"]:
                actor_ids.update(
                    e["payload"]["subject_id"] for e in exception["history"]
                )
            authorities = db.execute(
                "SELECT id,subject_id,role,version,payload,created_at FROM gov_grants WHERE tenant_id=%s ORDER BY created_at,id LIMIT 1001",
                (t["tenant_id"],),
            ).fetchall()
            if len(authorities) > 1000:
                raise ValueError("Authority history exceeds export limit")
            content["authority_history"] = [
                dict(
                    id=str(row[0]),
                    subject_id=row[1],
                    role=row[2],
                    version=row[3],
                    delegation=decode(row[4]),
                    created_at=str(row[5]),
                )
                for row in authorities
                if row[1] in actor_ids
            ]
            return dict(
                format="cloudsaver-governance-audit-v1",
                tenant_id=t["tenant_id"],
                finding_id=id,
                exported_at=self.clock().isoformat(),
                technical_only=True,
                currently_fresh=evidence.fresh(p["assessment"], self.clock()),
                current_verification_supported=self._current_support(
                    db, t, f, observation
                ),
                latest_observation_checked=observation is not None,
                content=content,
                manifest={k: digest(v) for k, v in content.items()},
                warning="Hash-linked application history and SHA-256 content digests require an independently retained trusted anchor for tamper evidence. No organizational compliance or absence of historical exposure is certified. Apply the approved retention/legal-hold policy.",
            )
