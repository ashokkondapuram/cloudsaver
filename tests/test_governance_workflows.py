"""Synthetic end-to-end governance decisions: never cloud writes or compliance certification."""

from datetime import datetime, timedelta, timezone
import hashlib, hmac, json, secrets
from types import SimpleNamespace
from uuid import uuid4, uuid5, NAMESPACE_URL
import pytest
from fastapi.testclient import TestClient
from app.auth import UserClaims, Role
from app.config import Settings
from app.store import Store, PostgresStore
from app.enterprise_store import EnterpriseStore
from app.main import create_app
from app.governance_store import Governance, GovernanceForbidden
from app.focus import digest
from tests.test_enterprise import TID, SUB
from tests.test_outcomes import financial_postgres  # noqa: F401 -- shared isolated database fixture

USERS = {
    name: str(uuid5(NAMESPACE_URL, "governance-test-" + name))
    for name in (
        "admin",
        "owner",
        "security",
        "approver",
        "verifier",
        "business",
        "auditor",
        "other",
    )
}


def auth(name="security"):
    return {"Authorization": "Bearer " + name}


@pytest.fixture
def gov(tmp_path, monkeypatch, request):
    monkeypatch.setenv("CLOUDSAVER_AUTH_MODE", "entra")
    monkeypatch.setenv("CLOUDSAVER_KEY_VERIFIER", "local")
    now = [datetime.now(timezone.utc) - timedelta(minutes=5)]
    tenant = dict(
        tenant_id=TID,
        name="Governance QA",
        subscription_ids=[SUB],
        plan_tier="ENTERPRISE",
    )
    url = (
        request.getfixturevalue("financial_postgres")
        if getattr(request, "param", "sqlite") == "postgres"
        else None
    )
    settings = Settings("azure", str(tmp_path / "gov.db"), (tenant,), url)
    store = PostgresStore(url) if url else Store(settings.database)
    db = EnterpriseStore(settings)
    repo = Governance(db, clock=lambda: now[0])
    monkeypatch.setattr("app.governance_api.Governance", lambda *_: repo)

    class Identity:
        def verify_token(self, value):
            return UserClaims(
                user_id=USERS[value],
                tenant_id=TID,
                roles=[Role.TENANT_ADMIN if value == "admin" else Role.VIEWER],
            )

    client = TestClient(create_app(settings, identity_validator=Identity()))
    resource = dict(
        cloud_provider="azure",
        scope_id=SUB,
        subscription_id=SUB,
        resource_id=f"/subscriptions/{SUB}/resourceGroups/qa/providers/Microsoft.Storage/storageAccounts/customer",
        resource_name="customer",
        resource_type="Microsoft.Storage/storageAccounts",
        evidence={"allow_blob_public_access": True, "tags": {"payload": "never-copy"}},
    )
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=now[0].isoformat(),
        mode="azure",
        status="completed",
        cloud_providers=["azure"],
        total_items_found=1,
        subscriptions_scanned=1,
        total_monthly_waste_usd=None,
        inventory=[resource],
        findings=[],
        scope_results=[dict(provider="azure", scope_id=SUB, status="completed")],
    )
    store.save(TID, scan, workspace=tenant)
    key = secrets.token_hex(32)
    source = dict(
        tenant_id=TID,
        source_id="gov-collector",
        providers=["azure"],
        scope_ids=[SUB],
        kinds=["implementation", "verification", "compensation", "correction"],
        key_env="CLOUDSAVER_GOVERNANCE_KEY_PRIMARY",
    )
    monkeypatch.setenv("CLOUDSAVER_GOVERNANCE_SOURCES", json.dumps([source]))
    monkeypatch.setenv(source["key_env"], key)
    s = SimpleNamespace(
        api=client,
        repo=repo,
        db=db,
        store=store,
        settings=settings,
        tenant=tenant,
        now=now,
        resource=resource,
        scan=scan,
        key=key,
        source=source,
    )
    for name, role in [
        ("admin", "ComplianceReviewer"),
        ("owner", "ResourceOwner"),
        ("security", "SecurityAnalyst"),
        ("approver", "ChangeApprover"),
        ("verifier", "ComplianceReviewer"),
        ("business", "BusinessRiskOwner"),
        ("auditor", "Auditor"),
        ("other", "SecurityAnalyst"),
    ]:
        r = client.put(
            "/api/v1/governance/access",
            headers=auth("admin"),
            json=dict(
                subject_id=USERS[name],
                role=role,
                version=0,
                expires_at=(now[0] + timedelta(days=60)).isoformat(),
                maximum_score=25 if name == "business" else 11,
                maximum_exception_days=30,
                authority_reference="QA-Delegation-Reviewed",
            ),
        )
        assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/governance/controls",
        headers=auth("admin"),
        json=dict(
            version=0,
            owner=USERS["verifier"],
            mandatory_obligation=False,
            risk_appetite=6,
            maximum_exception_days=30,
            rationale="Synthetic organizational policy reviewed for a discretionary pilot.",
            mappings=[],
        ),
    )
    assert r.status_code == 201, r.text
    return s


def context():
    return dict(
        application="payments",
        environment="production",
        classification="customer_data",
        technical_owner=USERS["owner"],
        business_owner=USERS["business"],
        rationale="Application owner confirmed the production customer-data classification.",
    )


def detect(s):
    r = s.api.post(
        "/api/v1/governance/assessments",
        headers=auth(),
        json=dict(
            scan_id=s.scan["scan_id"],
            resource_id=s.resource["resource_id"],
            context=context(),
        ),
    )
    assert r.status_code == 201, r.text
    return r.json()["finding"]


def risk(s, f):
    r = s.api.post(
        "/api/v1/governance/risks",
        headers=auth(),
        json=dict(
            request_key=str(uuid4()),
            finding_ids=[f["id"]],
            business_owner=USERS["business"],
            statement="Potential disclosure of customer information through public blob access.",
            treatment_plan="Review dependencies, disable public access and validate legitimate access.",
            inherent_likelihood=4,
            inherent_impact=5,
            residual_likelihood=1,
            residual_impact=4,
            review_date=str((s.now[0] + timedelta(days=40)).date()),
        ),
    )
    assert r.status_code == 201, r.text
    return s.api.get(
        "/api/v1/governance/findings/" + f["id"], headers=auth()
    ).json(), r.json()


def action(s, f, name, user="security", **fields):
    r = s.api.post(
        "/api/v1/governance/findings/" + f["id"] + "/actions",
        headers=auth(user),
        json=dict(
            version=f["version"],
            action=name,
            note="Synthetic reviewed decision with linked business evidence.",
            **fields,
        ),
    )
    assert r.status_code == 200, r.text
    return r.json()


def plan():
    return dict(
        change_reference="CHG-GOV-42",
        steps=["Set the exact account allowBlobPublicAccess flag to false."],
        dependency_checks=[
            "Confirm public-client dependency migration with the application owner."
        ],
        validation_steps=[
            "Read the account flag and exercise legitimate authenticated application access."
        ],
        rollback_plan="Restore the approved prior setting only through a separately approved change.",
    )


def prepared(s):
    f, r = risk(s, detect(s))
    f = action(s, f, "triage")
    f = action(s, f, "propose", user="owner", plan=plan())
    f = action(s, f, "approve", user="approver")
    return f, r


def receipt(s, f, kind, payload, **changes):
    raw = dict(
        receipt_id=str(uuid4()),
        tenant_id=TID,
        finding_id=f["id"],
        source_id=s.source["source_id"],
        kind=kind,
        issued_at=s.now[0].isoformat(),
        payload=payload,
        **changes,
    )
    signature = hmac.new(
        s.key.encode(),
        json.dumps(
            raw, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    r = s.api.post(
        "/api/v1/governance/evidence/receipts",
        headers={**auth("owner"), "X-Evidence-Signature": signature},
        json=raw,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], raw, signature


def implement(s, f):
    s.now[0] += timedelta(seconds=1)
    id, *_ = receipt(
        s,
        f,
        "implementation",
        dict(
            plan_digest=f["payload"]["plan"]["digest"],
            event_id="provider-" + str(uuid4()),
            operation="disable_blob_public_access",
            status="Succeeded",
            occurred_at=s.now[0].isoformat(),
        ),
    )
    return action(s, f, "implement", user="owner", receipt_id=id)


def observe(s, value=False):
    s.now[0] += timedelta(seconds=1)
    resource = dict(s.resource, evidence={"allow_blob_public_access": value})
    scan = dict(
        s.scan,
        scan_id=str(uuid4()),
        timestamp=s.now[0].isoformat(),
        inventory=[resource],
    )
    s.store.save(TID, scan, workspace=s.tenant)
    s.scan = scan
    return resource, scan


def verify(s, f):
    resource, scan = observe(s)
    from app.governance_evidence import evaluate

    assessment = evaluate(resource, scan, context(), f["payload"]["control"], s.now[0])
    s.now[0] += timedelta(seconds=1)
    id, *_ = receipt(
        s,
        f,
        "verification",
        dict(
            plan_digest=f["payload"]["plan"]["digest"],
            scan_id=scan["scan_id"],
            state_digest=assessment["state_digest"],
            observed_at=s.now[0].isoformat(),
            health_accepted=True,
            legitimate_access_accepted=True,
            validation_reference="QA-Application-Access-42",
        ),
    )
    return action(
        s, f, "verify", user="verifier", receipt_id=id, scan_id=scan["scan_id"]
    )


@pytest.mark.parametrize(
    "gov",
    ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)],
    indirect=True,
)
def test_full_finding_risk_fix_verification_export_and_drift(gov):
    s = gov
    f, r = prepared(s)
    assert f["state"] == "approved"
    assert (
        s.api.post(
            "/api/v1/governance/findings/" + f["id"] + "/actions",
            headers=auth(),
            json=dict(
                version=f["version"],
                action="close",
                note="Clicking close cannot establish verification.",
            ),
        ).status_code
        == 409
    )
    f = implement(s, f)
    f = verify(s, f)
    assert f["state"] == "verified"
    f = action(s, f, "close")
    assert f["state"] == "closed"
    package = s.api.get(
        "/api/v1/governance/findings/" + f["id"] + "/export", headers=auth("auditor")
    )
    assert package.status_code == 200, package.text
    p = package.json()
    assert (
        p["technical_only"]
        and p["manifest"]["finding"] == digest(p["content"]["finding"])
        and "never-copy" not in package.text
    )
    previous = "0" * 64
    for event in p["content"]["finding_history"]:
        assert event["previous_hash"] == previous
        assert (
            digest(
                dict(
                    tenant_id=TID,
                    entity_type="finding",
                    entity_id=f["id"],
                    version=event["version"],
                    previous_hash=previous,
                    payload=event["payload"],
                )
            )
            == event["event_hash"]
        )
        previous = event["event_hash"]
    observe(s, True)
    m = s.api.post("/api/v1/governance/monitor", headers=auth())
    assert m.status_code == 200, m.text
    reopened = s.api.get(
        "/api/v1/governance/findings/" + f["id"], headers=auth()
    ).json()
    assert (
        reopened["state"] == "reopened" and reopened["payload"]["verification"] is None
    )
    assert reopened["payload"]["assessment"]["result"] == "fail"


def exception_request(s, f):
    end = s.now[0] + timedelta(days=2)
    receipt_id, *_ = receipt(
        s,
        f,
        "compensation",
        dict(
            observed_at=s.now[0].isoformat(),
            valid_until=(end + timedelta(hours=1)).isoformat(),
            accepted=True,
            evaluation_reference="QA-Network-Guard-42",
            controls_summary="Signed review of compensating network and access controls for the exact target.",
        ),
    )
    r = s.api.post(
        "/api/v1/governance/exceptions",
        headers=auth("owner"),
        json=dict(
            request_key=str(uuid4()),
            finding_id=f["id"],
            justification="Application migration needs a bounded transition window.",
            rejected_alternatives="Immediate shutdown was assessed and rejected due to service continuity.",
            compensating_controls="Reviewed additional network access controls and monitored access logs.",
            compensation_receipt_id=receipt_id,
            remediation_plan="Complete migration and disable account public blob access.",
            start=(s.now[0] + timedelta(seconds=1)).isoformat(),
            end=end.isoformat(),
            review_at=(s.now[0] + timedelta(days=1)).isoformat(),
            review_trigger="Review on any network or application dependency change.",
        ),
    )
    assert r.status_code == 201, r.text
    return r.json()


def exception_decision(s, x, action, user):
    r = s.api.post(
        "/api/v1/governance/exceptions/" + x["id"] + "/actions",
        headers=auth(user),
        json=dict(
            version=x["version"],
            action=action,
            note="Reviewed exact scope, residual risk, authority and compensation.",
        ),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_accepted_risk_keeps_failure_and_expires_with_audit_escalation(gov):
    s = gov
    f, _ = risk(s, detect(s))
    f = action(s, f, "triage")
    x = exception_request(s, f)
    x = exception_decision(s, x, "review", "security")
    x = exception_decision(s, x, "approve", "business")
    assert x["state"] == "approved"
    s.now[0] += timedelta(seconds=2)
    assert s.api.post("/api/v1/governance/monitor", headers=auth()).status_code == 200
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert (
        f["state"] == "accepted_risk" and f["payload"]["assessment"]["result"] == "fail"
    )
    s.now[0] += timedelta(days=3)
    r = s.api.post("/api/v1/governance/monitor", headers=auth())
    assert r.status_code == 200, r.text
    x = s.api.get("/api/v1/governance/exceptions", headers=auth("auditor")).json()[
        "items"
    ][0]
    assert x["state"] == "expired"
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert f["state"] == "reopened"
    assert (
        s.api.get("/api/v1/governance/summary", headers=auth("auditor")).json()[
            "compliance_score"
        ]
        is None
    )


def test_risk_acceptance_requires_sufficient_independent_authority(gov):
    s = gov
    f, _ = risk(s, detect(s))
    f = action(s, f, "triage")
    x = exception_request(s, f)
    x = exception_decision(s, x, "review", "security")
    grants = s.api.get("/api/v1/governance/access", headers=auth("admin")).json()[
        "items"
    ]
    g = next(g for g in grants if g["role"] == "BusinessRiskOwner")
    r = s.api.put(
        "/api/v1/governance/access",
        headers=auth("admin"),
        json=dict(g, maximum_score=11),
    )
    assert r.status_code == 200, r.text
    r = s.api.post(
        "/api/v1/governance/exceptions/" + x["id"] + "/actions",
        headers=auth("business"),
        json=dict(
            version=x["version"],
            action="approve",
            note="A material risk exceeds this delegated authority.",
        ),
    )
    assert r.status_code == 409
    assert (
        s.api.post(
            "/api/v1/governance/exceptions/" + x["id"] + "/actions",
            headers=auth("owner"),
            json=dict(
                version=x["version"],
                action="approve",
                note="The resource owner cannot accept business risk.",
            ),
        ).status_code
        == 403
    )


def test_mandatory_policy_cannot_be_waived_or_downgraded(gov):
    s = gov
    policy = s.api.get("/api/v1/governance/controls", headers=auth()).json()["policy"]
    keys = (
        "version",
        "owner",
        "mandatory_obligation",
        "risk_appetite",
        "maximum_exception_days",
        "rationale",
        "mappings",
    )
    body = {k: policy[k] for k in keys}
    body["mandatory_obligation"] = True
    r = s.api.post("/api/v1/governance/controls", headers=auth("admin"), json=body)
    assert r.status_code == 201, r.text
    changed = r.json()
    body["version"] = changed["version"]
    body["mandatory_obligation"] = False
    assert (
        s.api.post(
            "/api/v1/governance/controls", headers=auth("admin"), json=body
        ).status_code
        == 409
    )
    f, _ = risk(s, detect(s))
    f = action(s, f, "triage")
    end = s.now[0] + timedelta(days=2)
    id, *_ = receipt(
        s,
        f,
        "compensation",
        dict(
            observed_at=s.now[0].isoformat(),
            valid_until=end.isoformat(),
            accepted=True,
            evaluation_reference="QA-42",
            controls_summary="Compensation does not remove a mandatory obligation.",
        ),
    )
    r = s.api.post(
        "/api/v1/governance/exceptions",
        headers=auth("owner"),
        json=dict(
            request_key=str(uuid4()),
            finding_id=f["id"],
            justification="A documented justification cannot override this obligation.",
            rejected_alternatives="Other alternatives need the organizational review process.",
            compensating_controls="Compensation cannot itself remove the mandatory requirement.",
            compensation_receipt_id=id,
            remediation_plan="Implement the reviewed mandatory control.",
            start=s.now[0].isoformat(),
            end=end.isoformat(),
            review_at=(end - timedelta(hours=1)).isoformat(),
            review_trigger="Follow the mandatory control review.",
        ),
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "role", ["owner", "security", "approver", "business", "auditor"]
)
def test_only_independent_compliance_reviewer_can_verify(gov, role):
    s = gov
    f, _ = prepared(s)
    f = implement(s, f)
    observe(s)
    r = s.api.post(
        "/api/v1/governance/findings/" + f["id"] + "/actions",
        headers=auth(role),
        json=dict(
            version=f["version"],
            action="verify",
            note="A different reviewer must assess the fix.",
            receipt_id=str(uuid4()),
            scan_id=s.scan["scan_id"],
        ),
    )
    assert r.status_code == 403


def test_older_passing_snapshot_cannot_hide_latest_drift(gov):
    s = gov
    f, _ = prepared(s)
    f = implement(s, f)
    f = verify(s, f)
    good = s.scan["scan_id"]
    observe(s, True)
    r = s.api.post(
        "/api/v1/governance/findings/" + f["id"] + "/actions",
        headers=auth(),
        json=dict(
            version=f["version"],
            action="close",
            note="An older passing snapshot cannot hide drift.",
            scan_id=good,
        ),
    )
    assert r.status_code == 409


def test_unknown_and_not_applicable_are_never_invented_passes(gov):
    s = gov
    observe(s, None)
    r = s.api.post(
        "/api/v1/governance/assessments",
        headers=auth(),
        json=dict(
            scan_id=s.scan["scan_id"],
            resource_id=s.resource["resource_id"],
            context=context(),
        ),
    )
    assert r.status_code == 201, r.text
    assert r.json()["assessment"]["result"] == "unknown"
    assert (
        s.api.get("/api/v1/governance/summary", headers=auth()).json()[
            "unknown_assessments"
        ]
        == 1
    )
    observe(s, False)
    c = context()
    c["environment"] = "nonproduction"
    r = s.api.post(
        "/api/v1/governance/assessments",
        headers=auth(),
        json=dict(
            scan_id=s.scan["scan_id"], resource_id=s.resource["resource_id"], context=c
        ),
    )
    assert r.status_code == 201 and r.json()["assessment"]["result"] == "not_applicable"


def test_auditor_cannot_mutate_and_api_key_cannot_decide(gov):
    s = gov
    f, _ = prepared(s)
    assert (
        s.api.post(
            "/api/v1/governance/findings/" + f["id"] + "/actions",
            headers=auth("auditor"),
            json=dict(
                version=f["version"],
                action="note",
                note="Auditors are read-only reviewers.",
            ),
        ).status_code
        == 403
    )
    from app.governance_api import latest_observation
    from app.governance_contracts import FindingAction

    key = dict(
        s.tenant,
        roles=["TenantAdmin"],
        subject_id=USERS["approver"],
        subject_type="user",
        key_id="synthetic-key",
    )
    with pytest.raises(GovernanceForbidden):
        s.repo.act(
            key,
            f["id"],
            FindingAction(
                version=f["version"],
                action="approve",
                note="Keys cannot exercise human decision authority.",
            ),
            latest_observation(s.store, key, f),
        )
    assert (
        s.api.get(
            "/api/v1/governance/findings/" + str(uuid4()), headers=auth("auditor")
        ).status_code
        == 404
    )


def test_expected_fix_observed_before_recording_implementation_keeps_approval(gov):
    s = gov
    f, _ = prepared(s)
    s.now[0] += timedelta(seconds=1)
    id, *_ = receipt(
        s,
        f,
        "implementation",
        dict(
            plan_digest=f["payload"]["plan"]["digest"],
            event_id="expected-fix",
            operation="disable_blob_public_access",
            status="Succeeded",
            occurred_at=s.now[0].isoformat(),
        ),
    )
    observe(s, False)
    assert s.api.post("/api/v1/governance/monitor", headers=auth()).status_code == 200
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert f["state"] == "approved" and f["payload"]["approval"]
    assert (
        action(s, f, "implement", user="owner", receipt_id=id)["state"] == "implemented"
    )


def test_stale_closed_evidence_reopens_without_cloud_calls(gov):
    s = gov
    f, _ = prepared(s)
    f = action(s, verify(s, implement(s, f)), "close")
    s.now[0] += timedelta(hours=25)
    r = s.api.post("/api/v1/governance/monitor", headers=auth())
    assert r.status_code == 200, r.text
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert (
        f["state"] == "reopened" and f["payload"]["assessment"]["result"] == "unknown"
    )


def test_incident_handoff_blocks_ordinary_closure_until_independent_clearance(gov):
    s = gov
    f = detect(s)
    f = action(s, f, "incident", incident_reference="IR-42")
    assert f["state"] == "incident_escalated"
    r = s.api.post(
        "/api/v1/governance/findings/" + f["id"] + "/actions",
        headers=auth(),
        json=dict(
            version=f["version"],
            action="resume",
            note="The same analyst cannot clear this incident.",
            incident_reference="IR-42",
        ),
    )
    assert r.status_code == 409
    f = action(s, f, "resume", user="other", incident_reference="IR-CLEARED-42")
    assert f["state"] == "reopened"


def test_new_passing_configuration_alone_cannot_refute_original_finding(gov):
    s = gov
    f, _ = risk(s, detect(s))
    f = action(s, f, "triage")
    f = action(s, f, "request_dismissal", user="owner", dismissal_kind="false_positive")
    observe(s, False)
    r = s.api.post(
        "/api/v1/governance/findings/" + f["id"] + "/actions",
        headers=auth(),
        json=dict(
            version=f["version"],
            action="dismiss",
            scan_id=s.scan["scan_id"],
            note="A changed configuration alone does not refute an original observation.",
        ),
    )
    assert r.status_code == 409
    id, *_ = receipt(
        s,
        f,
        "correction",
        dict(
            original_scan_id=f["payload"]["original_assessment"]["scan_id"],
            original_state_digest=f["payload"]["original_assessment"]["state_digest"],
            evaluated_at=s.now[0].isoformat(),
            false_positive_supported=True,
            refutation_reference="QA-Collector-Correction-42",
        ),
    )
    f = action(s, f, "dismiss", receipt_id=id, scan_id=s.scan["scan_id"])
    assert f["state"] == "dismissed"
    r = s.api.get("/api/v1/governance/risks", headers=auth("business")).json()["items"][
        0
    ]
    reviewed = s.api.post(
        "/api/v1/governance/risks/" + r["id"] + "/actions",
        headers=auth("business"),
        json=dict(
            version=r["version"],
            action="review",
            note="Business owner reviewed the corrected original evidence.",
        ),
    )
    assert reviewed.status_code == 200, reviewed.text
    retired = s.api.post(
        "/api/v1/governance/risks/" + r["id"] + "/actions",
        headers=auth("business"),
        json=dict(
            version=reviewed.json()["version"],
            action="retire",
            note="The independently reviewed finding is dismissed and current.",
        ),
    )
    assert retired.status_code == 200 and retired.json()["state"] == "retired"
    observe(s, True)
    assert s.api.post("/api/v1/governance/monitor", headers=auth()).status_code == 200
    assert (
        s.api.get("/api/v1/governance/risks", headers=auth()).json()["items"][0][
            "state"
        ]
        == "active"
    )


def test_passing_control_without_a_finding_counts_as_coverage(gov):
    s = gov
    observe(s, False)
    r = s.api.post(
        "/api/v1/governance/assessments",
        headers=auth(),
        json=dict(
            scan_id=s.scan["scan_id"],
            resource_id=s.resource["resource_id"],
            context=context(),
        ),
    )
    assert r.status_code == 201 and r.json()["finding"] is None
    summary = s.api.get("/api/v1/governance/summary", headers=auth()).json()
    assert (
        summary["assessed_resources"] == 1
        and summary["assessment_results"]["pass"] == 1
        and summary["unassessed_resource_coverage"] is None
    )


def test_receipts_are_tenant_bound_fresh_idempotent_and_tamper_checked(gov):
    s = gov
    f, _ = prepared(s)
    proof = dict(
        plan_digest=f["payload"]["plan"]["digest"],
        event_id="receipt-boundary",
        operation="disable_blob_public_access",
        status="Succeeded",
        occurred_at=s.now[0].isoformat(),
    )
    id, raw, signature = receipt(s, f, "implementation", proof)
    url = "/api/v1/governance/evidence/receipts"
    headers = {**auth("owner"), "X-Evidence-Signature": signature}
    r = s.api.post(url, headers=headers, json=raw)
    assert r.status_code == 201 and r.json() == dict(id=id, cached=True)
    for altered in (
        dict(raw, tenant_id=str(uuid4())),
        dict(raw, payload=dict(proof, event_id="forged")),
    ):
        assert s.api.post(url, headers=headers, json=altered).status_code == 422
    changed = dict(raw, payload=dict(proof, event_id="different"))
    signed = hmac.new(
        s.key.encode(),
        json.dumps(changed, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert (
        s.api.post(
            url, headers={**auth("owner"), "X-Evidence-Signature": signed}, json=changed
        ).status_code
        == 409
    )
    s.now[0] += timedelta(minutes=6)
    assert s.api.post(url, headers=headers, json=raw).status_code == 422
    assert (
        s.api.post(url, headers=auth("owner"), json={"trusted": True}).status_code
        == 422
    )


def test_revoked_collector_withholds_closure_and_reopens_closed_record(
    gov, monkeypatch
):
    s = gov
    f, _ = prepared(s)
    f = verify(s, implement(s, f))
    f = action(s, f, "close")
    monkeypatch.setenv("CLOUDSAVER_GOVERNANCE_SOURCES", "[]")
    r = s.api.post("/api/v1/governance/monitor", headers=auth())
    assert r.status_code == 200, r.text
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert (
        f["state"] == "reopened"
        and f["payload"]["reopen_reason"]
        == "VERIFICATION_OR_COLLECTOR_AUTHORITY_CHANGED"
    )


@pytest.mark.parametrize("change", ["expiry", "revocation"])
def test_unused_change_approval_does_not_survive_expiry_or_revocation(gov, change):
    s = gov
    f, _ = prepared(s)
    if change == "expiry":
        s.now[0] += timedelta(hours=25)
    else:
        grants = s.api.get("/api/v1/governance/access", headers=auth("admin")).json()[
            "items"
        ]
        g = next(g for g in grants if g["role"] == "ChangeApprover")
        assert (
            s.api.put(
                "/api/v1/governance/access",
                headers=auth("admin"),
                json=dict(g, active=False),
            ).status_code
            == 200
        )
    assert s.api.post("/api/v1/governance/monitor", headers=auth()).status_code == 200
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert f["state"] == "reopened"


def test_exception_rejection_revocation_and_policy_review_are_auditable(gov):
    s = gov
    f, _ = risk(s, detect(s))
    f = action(s, f, "triage")
    first = exception_request(s, f)
    first = exception_decision(s, first, "reject", "security")
    assert first["state"] == "rejected"
    x = exception_request(s, f)
    x = exception_decision(s, x, "review", "security")
    x = exception_decision(s, x, "approve", "business")
    x = exception_decision(s, x, "revoke", "business")
    assert x["state"] == "revoked"
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert f["state"] == "reopened"
    assert (
        len(
            s.api.get(
                "/api/v1/governance/findings/" + f["id"] + "/export",
                headers=auth("auditor"),
            ).json()["content"]["exceptions"]
        )
        == 2
    )


def test_actor_roles_cannot_be_self_approved_or_implicitly_inherited(gov):
    s = gov
    f, _ = risk(s, detect(s))
    f = action(s, f, "triage")
    f = action(s, f, "propose", user="owner", plan=plan())
    owner_approver = dict(
        subject_id=USERS["owner"],
        role="ChangeApprover",
        version=0,
        expires_at=(s.now[0] + timedelta(days=30)).isoformat(),
        authority_reference="QA-Role-Not-SoD",
    )
    assert (
        s.api.put(
            "/api/v1/governance/access", headers=auth("admin"), json=owner_approver
        ).status_code
        == 200
    )
    assert (
        s.api.post(
            "/api/v1/governance/findings/" + f["id"] + "/actions",
            headers=auth("owner"),
            json=dict(
                version=f["version"],
                action="approve",
                note="The proposer cannot approve their own change.",
            ),
        ).status_code
        == 409
    )
    assert (
        s.api.put(
            "/api/v1/governance/access", headers=auth("owner"), json=owner_approver
        ).status_code
        == 403
    )
    assert (
        s.api.post(
            "/api/v1/governance/findings/" + f["id"] + "/actions",
            headers=auth("admin"),
            json=dict(
                version=f["version"],
                action="approve",
                note="TenantAdmin alone does not grant change approval.",
            ),
        ).status_code
        == 403
    )


def test_scope_unknown_health_failure_and_plan_drift_cannot_close(gov):
    s = gov
    f, _ = prepared(s)
    f = implement(s, f)
    resource, scan = observe(s, False)
    from app.governance_evidence import evaluate

    a = evaluate(resource, scan, context(), f["payload"]["control"], s.now[0])
    s.now[0] += timedelta(seconds=1)
    id, *_ = receipt(
        s,
        f,
        "verification",
        dict(
            plan_digest=f["payload"]["plan"]["digest"],
            scan_id=scan["scan_id"],
            state_digest=a["state_digest"],
            observed_at=s.now[0].isoformat(),
            health_accepted=False,
            legitimate_access_accepted=True,
            validation_reference="QA-Failed-Health",
        ),
    )
    r = s.api.post(
        "/api/v1/governance/findings/" + f["id"] + "/actions",
        headers=auth("verifier"),
        json=dict(
            version=f["version"],
            action="verify",
            note="A private account without healthy application access is insufficient.",
            receipt_id=id,
            scan_id=scan["scan_id"],
        ),
    )
    assert r.status_code == 409
    assert (
        s.api.post(
            "/api/v1/governance/findings/" + f["id"] + "/actions",
            headers=auth(),
            json=dict(
                version=f["version"] - 1,
                action="note",
                note="A stale write must not overwrite a decision.",
            ),
        ).status_code
        == 409
    )


def test_governance_worker_only_reassesses_local_saved_data(gov, monkeypatch):
    s = gov
    f, _ = prepared(s)
    f = action(s, verify(s, implement(s, f)), "close")
    observe(s, True)
    from workers import governance_monitor

    monkeypatch.setattr(governance_monitor, "Governance", lambda *_: s.repo)
    result = governance_monitor.run_once(s.settings)
    assert result == dict(findings_checked=1, failed_workspaces=0, external_calls=0)
    assert (
        s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()[
            "state"
        ]
        == "reopened"
    )


@pytest.mark.postgres
@pytest.mark.parametrize("gov", ["postgres"], indirect=True)
def test_governance_rls_append_permissions_concurrency_and_rollback_guard(gov):
    import os, subprocess, sys
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlsplit, urlunsplit
    import psycopg
    from psycopg import errors, sql
    from app.governance_contracts import FindingAction
    from app.governance_schema import TABLES
    from app.governance_store import GovernanceConflict

    s = gov
    f, _ = prepared(s)
    t = dict(
        s.tenant, roles=["Viewer"], subject_id=USERS["security"], subject_type="user"
    )

    def decide(_):
        try:
            s.repo.act(
                t,
                f["id"],
                FindingAction(
                    version=f["version"],
                    action="note",
                    note="Concurrent analyst notes retain one consistent history.",
                ),
            )
            return "saved"
        except GovernanceConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decide, range(2))) == ["conflict", "saved"]
    for table in TABLES:
        with psycopg.connect(s.db.url) as db:
            assert db.execute(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
                (table,),
            ).fetchone() == (True, True)
            assert (
                db.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                == 0
            )
            db.execute(
                "SELECT set_config('app.current_tenant_id',%s,true)", (str(uuid4()),)
            )
            assert (
                db.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                == 0
            )
    for statement in (
        "UPDATE gov_events SET payload=payload",
        "DELETE FROM gov_receipts",
        "UPDATE gov_grants SET payload=payload",
        "DELETE FROM gov_controls",
        "UPDATE gov_assessments SET payload=payload",
        "DELETE FROM gov_actions",
        "UPDATE gov_findings SET tenant_id=tenant_id",
    ):
        with psycopg.connect(s.db.url) as db:
            db.execute("SELECT set_config('app.current_tenant_id',%s,true)", (TID,))
            with pytest.raises(errors.InsufficientPrivilege):
                db.execute(statement)
    owner = urlunsplit(
        urlsplit(os.environ["CLOUDSAVER_TEST_OWNER_URL"])._replace(
            path=urlsplit(s.db.url).path
        )
    )
    rollback = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0022_financial_outcomes"],
        env={**os.environ, "CLOUDSAVER_MIGRATION_URL": owner},
        capture_output=True,
        text=True,
    )
    assert rollback.returncode != 0 and "data-preserving rollback" in rollback.stderr
    with psycopg.connect(s.db.url) as db:
        assert db.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE oid='gov_findings'::regclass"
        ).fetchone()[0]


def test_historical_approval_survives_approver_departure_after_implementation(gov):
    s = gov
    f, _ = prepared(s)
    f = implement(s, f)
    grant = next(
        g
        for g in s.api.get("/api/v1/governance/access", headers=auth("admin")).json()[
            "items"
        ]
        if g["role"] == "ChangeApprover"
    )
    assert (
        s.api.put(
            "/api/v1/governance/access",
            headers=auth("admin"),
            json=dict(grant, active=False),
        ).status_code
        == 200
    )
    f = verify(s, f)
    assert action(s, f, "close")["state"] == "closed"


def test_new_collector_can_reattest_same_authorized_event_without_reexecution(
    gov, monkeypatch
):
    s = gov
    f, _ = prepared(s)
    f = action(s, verify(s, implement(s, f)), "close")
    original = f["payload"]["implementation"]
    monkeypatch.setenv("CLOUDSAVER_GOVERNANCE_SOURCES", "[]")
    assert s.api.post("/api/v1/governance/monitor", headers=auth()).status_code == 200
    f = s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()
    assert f["state"] == "reopened"
    source = dict(s.source, source_id="replacement-collector")
    s.source = source
    monkeypatch.setenv("CLOUDSAVER_GOVERNANCE_SOURCES", json.dumps([source]))
    s.now[0] += timedelta(seconds=1)
    id, *_ = receipt(
        s,
        f,
        "implementation",
        dict(
            plan_digest=f["payload"]["plan"]["digest"],
            event_id=original["event_id"],
            operation="disable_blob_public_access",
            status="Succeeded",
            occurred_at=original["occurred_at"],
        ),
    )
    f = action(s, f, "implement", user="owner", receipt_id=id)
    f = action(s, verify(s, f), "close")
    assert f["state"] == "closed"
    with s.db.transaction(TID) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM gov_actions WHERE tenant_id=%s", (TID,)
            ).fetchone()[0]
            == 1
        )


def test_stored_evidence_tampering_is_detected_before_relying_on_a_closed_finding(gov):
    s = gov
    f, _ = prepared(s)
    f = action(s, verify(s, implement(s, f)), "close")
    receipt_id = f["payload"]["verification"]["receipt_id"]
    # Emulate privileged corruption in the disposable SQLite fixture only.
    # Separate PostgreSQL tests prove the runtime role cannot make this write.
    with s.db.transaction(TID, write=True) as db:
        db.execute("DROP TRIGGER gov_receipts_no_update")
        from app.enterprise_store import decode

        proof = decode(
            db.execute(
                "SELECT payload FROM gov_receipts WHERE id=%s", (receipt_id,)
            ).fetchone()[0]
        )
        proof["health_accepted"] = False
        db.execute(
            "UPDATE gov_receipts SET payload=%s WHERE id=%s",
            (db.json(proof), receipt_id),
        )
    package = s.api.get(
        "/api/v1/governance/findings/" + f["id"] + "/export", headers=auth("auditor")
    )
    assert (
        package.status_code == 200
        and not package.json()["current_verification_supported"]
    )
    assert s.api.post("/api/v1/governance/monitor", headers=auth()).status_code == 200
    assert (
        s.api.get("/api/v1/governance/findings/" + f["id"], headers=auth()).json()[
            "state"
        ]
        == "reopened"
    )


def test_event_chain_tampering_blocks_an_audit_export(gov):
    s = gov
    f = detect(s)
    with s.db.transaction(TID, write=True) as db:
        db.execute("DROP TRIGGER gov_events_no_update")
        db.execute(
            "UPDATE gov_events SET event_hash=%s WHERE tenant_id=%s AND entity_type=%s AND entity_id=%s",
            ("a" * 64, TID, "finding", f["id"]),
        )
    r = s.api.get(
        "/api/v1/governance/findings/" + f["id"] + "/export", headers=auth("auditor")
    )
    assert r.status_code == 409 and "integrity" in r.json()["detail"]


@pytest.mark.parametrize(
    ("flag", "expected"),
    [(True, "fail"), (False, "pass"), (None, "unknown"), ("true", "unknown")],
)
def test_live_storage_projection_requires_an_actual_boolean_and_omits_raw_tags(
    gov, monkeypatch, flag, expected
):
    from app.scanner import scan_inventory_observations
    from app.governance_evidence import evaluate

    s = gov
    row = dict(
        id=s.resource["resource_id"],
        name="customer",
        type="Microsoft.Storage/storageAccounts",
        resourceGroup="qa",
        subscriptionId=SUB,
        location="eastus",
        allowBlobPublicAccess=flag,
        tags={"payload": "never-copy-raw-customer-tags"},
    )
    monkeypatch.setattr("app.scanner.execute_pages", lambda *args: [row])
    observed = scan_inventory_observations(None, [SUB])[0]
    policy = s.api.get("/api/v1/governance/controls", headers=auth()).json()["policy"]
    result = evaluate(observed, s.scan, context(), policy, s.now[0])
    assert result["result"] == expected
    assert "never-copy-raw-customer-tags" not in json.dumps(result)


@pytest.mark.parametrize(
    "gov",
    ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)],
    indirect=True,
)
def test_unrelated_receipt_history_cannot_hide_a_newer_negative_check(gov):
    s = gov
    f, _ = prepared(s)
    f = action(s, verify(s, implement(s, f)), "close")
    base = dict(
        scan_id=s.scan["scan_id"],
        state_digest=f["payload"]["assessment"]["state_digest"],
        observed_at=s.now[0].isoformat(),
        health_accepted=False,
        legitimate_access_accepted=True,
        validation_reference="QA-Newer-Failed-Health",
    )
    s.now[0] += timedelta(seconds=1)
    receipt(
        s, f, "verification", dict(base, plan_digest=f["payload"]["plan"]["digest"])
    )
    for index in range(102):
        s.now[0] += timedelta(microseconds=1)
        receipt(
            s,
            f,
            "verification",
            dict(base, plan_digest=digest(["unrelated-plan", index])),
        )
    package = s.api.get(
        "/api/v1/governance/findings/" + f["id"] + "/export", headers=auth("auditor")
    )
    assert (
        package.status_code == 200
        and not package.json()["current_verification_supported"]
    )
