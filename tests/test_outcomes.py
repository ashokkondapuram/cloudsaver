"""Signed synthetic finance/health proofs exercise real stores and human-role API gates."""

from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace
import hashlib, hmac, json, secrets, os, subprocess, sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import psycopg
from psycopg import sql, errors
import pytest
from fastapi.testclient import TestClient
from app.auth import UserClaims, Role
from app.config import Settings
from app.store import Store
from app.enterprise_store import EnterpriseStore
from app.focus import FocusRepository, ImportRequest
from app.main import create_app
from app.outcome_store import Outcomes
from app.outcome_anomalies import Investigations
from app.outcome_evidence import configuration, digest
from tests.test_enterprise import TID, SUB

UIDS = {
    "engineer": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "finance": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "viewer": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
}


@pytest.fixture
def outcomes(tmp_path, monkeypatch, request):
    monkeypatch.setenv("CLOUDSAVER_AUTH_MODE", "entra")
    monkeypatch.setenv("CLOUDSAVER_KEY_VERIFIER", "local")
    now = [
        datetime.combine(
            datetime.now(timezone.utc).date() - timedelta(days=65),
            time.min,
            timezone.utc,
        )
    ]
    tenant = dict(
        tenant_id=TID, name="Outcome QA", subscription_ids=[SUB], plan_tier="ENTERPRISE"
    )
    database_url = (
        request.getfixturevalue("financial_postgres")
        if getattr(request, "param", "sqlite") == "postgres"
        else None
    )
    settings = Settings("azure", str(tmp_path / "outcomes.db"), (tenant,), database_url)
    from app.store import PostgresStore

    store = PostgresStore(database_url) if database_url else Store(settings.database)
    repo = EnterpriseStore(settings)
    resource = dict(
        cloud_provider="azure",
        scope_id=SUB,
        subscription_id=SUB,
        resource_id=f"/subscriptions/{SUB}/resourceGroups/qa/providers/Microsoft.Compute/virtualMachines/test",
        resource_name="synthetic-vm",
        resource_type="Microsoft.Compute/virtualMachines",
        region="eastus",
        evidence={"vm_size": "D4"},
    )
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=now[0].isoformat(),
        mode="azure",
        status="completed",
        cloud_providers=["azure"],
        subscriptions_scanned=1,
        total_items_found=1,
        total_monthly_waste_usd=None,
        inventory=[resource],
        findings=[],
        scope_results=[
            dict(
                provider="azure",
                scope_id=SUB,
                status="completed",
                supported_inventory_complete=True,
                supported_resource_types=[resource["resource_type"]],
                regions=["eastus"],
            )
        ],
    )
    store.save(TID, scan, workspace=tenant)
    cases = Outcomes(repo, clock=lambda: now[0])
    investigations = Investigations(repo, clock=lambda: now[0])
    monkeypatch.setattr("app.outcome_api.Outcomes", lambda *_: cases)
    monkeypatch.setattr("app.outcome_api.Investigations", lambda *_: investigations)
    key = secrets.token_hex(32)
    source = dict(
        tenant_id=TID,
        source_id="qa-collector",
        providers=["azure"],
        kinds=["audit", "billing", "slo"],
        scope_ids=[SUB],
        key_env="CLOUDSAVER_EVIDENCE_KEY_OUTCOMES",
    )
    monkeypatch.setenv("CLOUDSAVER_EVIDENCE_SOURCES", json.dumps([source]))
    monkeypatch.setenv(source["key_env"], key)

    class Identity:
        def verify_token(self, value):
            return UserClaims(
                user_id=UIDS[value],
                tenant_id=TID,
                roles=[
                    {
                        "engineer": Role.TENANT_ADMIN,
                        "finance": Role.BILLING_ADMIN,
                        "viewer": Role.VIEWER,
                    }[value]
                ],
            )

    api = TestClient(create_app(settings, identity_validator=Identity()))
    return SimpleNamespace(
        api=api,
        cases=cases,
        investigations=investigations,
        repo=repo,
        store=store,
        tenant=tenant,
        resource=resource,
        scan=scan,
        now=now,
        key=key,
        source=source,
    )


def headers(user="engineer"):
    return {"Authorization": "Bearer " + user}


def create_case(s):
    r = s.api.post(
        "/api/v1/outcomes/cases",
        headers=headers(),
        json=dict(
            scan_id=s.scan["scan_id"],
            resource_id=s.resource["resource_id"],
            request_key=str(uuid4()),
            action="rightsizing",
            proposal="Resize the verified VM after owner and reliability review.",
        ),
    )
    assert r.status_code == 201, r.text
    return r.json()


def act(s, case, action, user="engineer", **fields):
    r = s.api.post(
        "/api/v1/outcomes/cases/" + case["id"] + "/actions",
        headers=headers(user),
        json=dict(
            version=case["version"],
            action=action,
            note="Synthetic change review evidence",
            **fields,
        ),
    )
    assert r.status_code == 200, r.text
    return r.json()


def approve(s, case):
    case = act(s, case, "assign", owner="team-platform")
    case = act(s, case, "review")
    return act(s, case, "approve", change_reference="CHG-42")


def receipt(s, case, kind, payload, **changes):
    body = dict(
        receipt_id=str(uuid4()),
        source_id="qa-collector",
        tenant_id=TID,
        case_id=case["id"],
        provider="azure",
        scope_id=SUB,
        resource_id=case["resource_id"],
        kind=kind,
        issued_at=s.now[0].isoformat(),
        payload=payload,
        **changes,
    )
    signature = hmac.new(
        s.key.encode(),
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    r = s.api.post(
        "/api/v1/outcomes/evidence/receipts",
        headers={**headers("finance"), "X-Evidence-Signature": signature},
        json=body,
    )
    assert r.status_code == 201, r.text
    return r.json(), body, signature


def prepare_proofs(s, case, reconciled=True, event_id=None):
    approved = datetime.fromisoformat(case["payload"]["approved_at"])
    event = approved + timedelta(hours=1)
    start = (event + timedelta(days=1)).date()
    end = start + timedelta(days=30)
    post = dict(s.resource, evidence={"vm_size": "D2"})
    s.now[0] = datetime.combine(end, time.min, timezone.utc) + timedelta(hours=2)
    scan = dict(
        s.scan,
        scan_id=str(uuid4()),
        timestamp=(s.now[0] - timedelta(hours=1)).isoformat(),
        inventory=[post],
    )
    s.store.save(TID, scan, workspace=s.tenant)
    baseline_end = approved.date()
    baseline_start = baseline_end - timedelta(days=30)
    records = []
    for label, a, b, amount in [
        ("before", baseline_start, baseline_end, "100"),
        ("after", start, end, "60"),
    ]:
        for i in range((b - a).days):
            day = a + timedelta(days=i)
            records.append(
                dict(
                    x_ChargeId=label + "-" + str(day),
                    ProviderName="Azure",
                    BillingAccountId=SUB,
                    SubAccountId=SUB,
                    BillingCurrency="USD",
                    ChargePeriodStart=datetime.combine(
                        day, time.min, timezone.utc
                    ).isoformat(),
                    ChargePeriodEnd=datetime.combine(
                        day + timedelta(days=1), time.min, timezone.utc
                    ).isoformat(),
                    ResourceId=case["resource_id"],
                    ChargeCategory="Usage",
                    BilledCost=amount,
                    EffectiveCost=amount,
                )
            )
    FocusRepository(s.repo).import_records(
        s.tenant,
        ImportRequest(
            source_id="synthetic-outcome-export",
            provider="azure",
            sub_account_id=SUB,
            billing_currency="USD",
            period_start=baseline_start,
            period_end=end,
            complete=False,
            records=records,
        ),
    )
    query = dict(
        baseline_start=str(baseline_start),
        baseline_end=str(baseline_end),
        post_start=str(start),
        post_end=str(end),
        currency="USD",
    )
    ledger = s.api.get(
        "/api/v1/outcomes/cases/" + case["id"] + "/billing-evidence",
        headers=headers("finance"),
        params=query,
    ).json()
    audit = dict(
        event_id=event_id or str(uuid4()),
        operation="resize",
        status="Succeeded",
        occurred_at=event.isoformat(),
        before_configuration_digest=case["payload"]["configuration_digest"],
        after_configuration_digest=digest(configuration(post)),
    )
    health = dict(
        window_start=datetime.combine(start, time.min, timezone.utc).isoformat(),
        window_end=datetime.combine(end, time.min, timezone.utc).isoformat(),
        policy_reference="SLO-QA-v1",
        health_accepted=True,
        utilization_accepted=True,
        utilization_summary="Synthetic utilization and health meet the approved evaluation policy.",
        configuration_digest=digest(configuration(post)),
    )
    billing = dict(
        query,
        baseline_recurring_cost="3000",
        post_recurring_cost="1800",
        added_recurring_cost="100",
        retained_commitment_cost="500",
        baseline_billed_cost="3000",
        post_billed_cost="1800",
        transition_cost="50",
        counterfactual_adjustment="-20",
        baseline_business_units="3000",
        post_business_units="6000",
        business_unit="transactions",
        normalization_method="business_volume_ratio",
        coverage_complete=True,
        commitments_accounted_for=True,
        credits_accounted_for=True,
        provider_reconciled=reconciled,
        invoice_reference="INV-QA-42" if reconciled else None,
        ledger_digest=ledger["digest"],
    )
    receipt(s, case, "audit", audit)
    receipt(s, case, "slo", health)
    receipt(s, case, "billing", billing)
    return scan, billing, health, audit


@pytest.mark.parametrize(
    "outcomes",
    ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)],
    indirect=True,
)
def test_human_lifecycle_separates_run_rate_and_reconciled_benefit(outcomes):
    s = outcomes
    case = approve(s, create_case(s))
    post, *_ = prepare_proofs(s, case)
    case = act(s, case, "implement")
    assert case["state"] == "implemented"
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    assert (
        case["state"] == "validated"
        and case["verification"]["validated_run_rate_reduction"] == "3600.00000000"
    )
    assert case["verification"]["reconciled_financial_benefit"] is None
    wrong = s.api.post(
        "/api/v1/outcomes/cases/" + case["id"] + "/actions",
        headers=headers(),
        json=dict(
            version=case["version"],
            action="reconcile",
            note="Independent finance review",
            scan_id=post["scan_id"],
        ),
    )
    assert wrong.status_code == 409
    case = act(s, case, "reconcile", user="finance", scan_id=post["scan_id"])
    assert (
        case["state"] == "financially_reconciled"
        and case["verification"]["reconciled_financial_benefit"] == "3530.00000000"
    )
    detail = s.api.get(
        "/api/v1/outcomes/cases/" + case["id"], headers=headers("finance")
    ).json()
    assert detail["financial_evidence_current"] and len(detail["events"]) == 7
    summary = s.api.get("/api/v1/outcomes/summary", headers=headers("finance")).json()
    assert (
        summary["validated_outcome_pct"] == 100
        and summary["currencies"][0]["estimated_opportunity"] is None
    )
    assert summary["currencies"][0]["reconciled_financial_benefit"] == "3530.00000000"


def test_regular_billing_imports_cannot_self_attest_and_missing_health_stays_unknown(
    outcomes,
):
    s = outcomes
    case = approve(s, create_case(s))
    r = s.api.post(
        "/api/v1/outcomes/cases/" + case["id"] + "/actions",
        headers=headers(),
        json=dict(
            version=case["version"],
            action="implement",
            note="Imported charges alone are insufficient",
        ),
    )
    assert r.status_code == 409
    r = s.api.post(
        "/api/v1/outcomes/evidence/receipts",
        headers=headers("finance"),
        json={"trusted": True},
    )
    assert r.status_code == 422
    assert (
        s.api.get("/api/v1/outcomes/cases", headers=headers("viewer")).status_code
        == 403
    )
    assert (
        s.api.get(
            "/api/v1/outcomes/cases/" + str(uuid4()), headers=headers("finance")
        ).status_code
        == 404
    )


def test_collector_revocation_and_billing_corrections_withhold_current_claim(
    outcomes, monkeypatch
):
    s = outcomes
    case = approve(s, create_case(s))
    post, bill, _, _ = prepare_proofs(s, case)
    case = act(s, case, "implement")
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    case = act(s, case, "reconcile", user="finance", scan_id=post["scan_id"])
    monkeypatch.setenv("CLOUDSAVER_EVIDENCE_SOURCES", "[]")
    detail = s.api.get(
        "/api/v1/outcomes/cases/" + case["id"], headers=headers("finance")
    ).json()
    assert (
        not detail["financial_evidence_current"]
        and not detail["run_rate_evidence_current"]
    )
    assert (
        s.cases.summary(s.tenant)["currencies"][0]["reconciled_financial_benefit"]
        is None
    )
    monkeypatch.setenv("CLOUDSAVER_EVIDENCE_SOURCES", json.dumps([s.source]))
    before_version = case["version"]
    day = date.fromisoformat(bill["post_start"])
    row = dict(
        x_ChargeId="correction",
        ProviderName="Azure",
        BillingAccountId=SUB,
        SubAccountId=SUB,
        BillingCurrency="USD",
        ChargePeriodStart=datetime.combine(day, time.min, timezone.utc),
        ChargePeriodEnd=datetime.combine(
            day + timedelta(days=1), time.min, timezone.utc
        ),
        ResourceId=case["resource_id"],
        ChargeCategory="Adjustment",
        BilledCost="5",
        EffectiveCost="5",
    )
    FocusRepository(s.repo).import_records(
        s.tenant,
        ImportRequest(
            source_id="corrected-invoice",
            provider="azure",
            sub_account_id=SUB,
            billing_currency="USD",
            period_start=day,
            period_end=day + timedelta(days=1),
            complete=False,
            records=[row],
        ),
    )
    detail = s.api.get(
        "/api/v1/outcomes/cases/" + case["id"], headers=headers("finance")
    ).json()
    assert (
        not detail["financial_evidence_current"] and detail["version"] == before_version
    )
    assert detail["financial_claims"][0]["recorded_amount"] == "3530.00000000"


def test_reconciliation_revision_is_append_only_not_additive(outcomes):
    s = outcomes
    case = approve(s, create_case(s))
    post, bill, _, _ = prepare_proofs(s, case)
    case = act(s, case, "implement")
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    case = act(s, case, "reconcile", user="finance", scan_id=post["scan_id"])
    s.now[0] += timedelta(seconds=1)
    receipt(s, case, "billing", dict(bill, counterfactual_adjustment="-120"))
    assert (
        s.cases.summary(s.tenant)["currencies"][0]["reconciled_financial_benefit"]
        is None
    )
    case = act(s, case, "reconcile", user="finance", scan_id=post["scan_id"])
    assert case["verification"]["reconciled_financial_benefit"] == "3430.00000000"
    detail = s.cases.detail(s.tenant, case["id"])
    assert (
        len(detail["financial_claims"]) == 2
        and detail["financial_claims"][0]["revision"] == 2
    )
    assert (
        s.cases.summary(s.tenant)["currencies"][0]["reconciled_financial_benefit"]
        == "3430.00000000"
    )
    again = act(s, case, "reconcile", user="finance", scan_id=post["scan_id"])
    assert again["version"] == case["version"]


def test_demand_and_retained_commitments_can_show_a_negative_outcome(outcomes):
    s = outcomes
    case = approve(s, create_case(s))
    post, bill, _, _ = prepare_proofs(s, case)
    s.now[0] += timedelta(seconds=1)
    receipt(s, case, "billing", dict(bill, post_business_units="1500"))
    case = act(s, case, "implement")
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    assert case["verification"]["validated_run_rate_reduction"] == "-900.00000000"
    case = act(s, case, "reconcile", user="finance", scan_id=post["scan_id"])
    assert case["verification"]["reconciled_financial_benefit"] == "-970.00000000"


def import_daily(s, *, missing=False, source="anomaly-window"):
    target = s.now[0].date() - timedelta(days=3)
    start = target - timedelta(days=28)
    records = []
    for i in range(29):
        day = start + timedelta(days=i)
        if missing and i != 28:
            continue
        value = "80" if day == target else "10"
        records.append(
            dict(
                x_ChargeId=source + "-" + str(day),
                ProviderName="Azure",
                BillingAccountId=SUB,
                SubAccountId=SUB,
                BillingCurrency="USD",
                ChargePeriodStart=datetime.combine(day, time.min, timezone.utc),
                ChargePeriodEnd=datetime.combine(
                    day + timedelta(days=1), time.min, timezone.utc
                ),
                ResourceId=s.resource["resource_id"],
                ChargeCategory="Usage",
                BilledCost=value,
                EffectiveCost=value,
            )
        )
    FocusRepository(s.repo).import_records(
        s.tenant,
        ImportRequest(
            source_id=source,
            provider="azure",
            sub_account_id=SUB,
            billing_currency="USD",
            period_start=start,
            period_end=target + timedelta(days=1),
            complete=False,
            records=records,
        ),
    )
    return target


def test_ownership_routes_deduplicated_cost_investigations_and_preserves_history(
    outcomes,
):
    s = outcomes
    day = import_daily(s)
    mapping = dict(
        scan_id=s.scan["scan_id"],
        resource_id=s.resource["resource_id"],
        version=0,
        application="payments",
        team="platform",
        owner="team-platform",
        environment="production",
        cost_center="cc-42",
    )
    r = s.api.put("/api/v1/outcomes/ownership", headers=headers(), json=mapping)
    assert r.status_code == 200, r.text
    assert (
        s.api.put(
            "/api/v1/outcomes/ownership", headers=headers(), json=mapping
        ).status_code
        == 409
    )
    detected = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    )
    assert detected.status_code == 200, detected.text
    items = detected.json()["items"]
    assert len(items) == 1
    anomaly = items[0]
    assert (
        anomaly["payload"]["owner"] == "team-platform"
        and Decimal(anomaly["payload"]["increase"]) == 70
    )
    assert (
        anomaly["payload"]["usage_vs_price"].startswith("unavailable")
        and anomaly["payload"]["billing_lag_days"] == 3
    )
    again = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    ).json()["items"][0]
    assert anomaly["id"] == again["id"] and again["version"] == 1
    for action in ("acknowledge", "investigate", "resolve"):
        body = dict(
            version=anomaly["version"],
            action=action,
            note="Reviewed with the responsible application owner.",
        )
        if action == "resolve":
            body["resolution"] = "actionable"
        r = s.api.post(
            "/api/v1/outcomes/anomalies/" + anomaly["id"] + "/actions",
            headers=headers("finance"),
            json=body,
        )
        assert r.status_code == 200, r.text
        anomaly = r.json()
    metrics = s.api.get(
        "/api/v1/outcomes/anomalies/metrics", headers=headers("finance")
    ).json()
    assert metrics["actionable_resolved_pct"] == 100 and metrics["unassigned"] == 0
    assert (
        s.api.get(
            "/api/v1/outcomes/anomalies/" + str(uuid4()), headers=headers("finance")
        ).status_code
        == 404
    )
    mapping.update(version=1, owner="team-product")
    assert (
        s.api.put(
            "/api/v1/outcomes/ownership", headers=headers(), json=mapping
        ).status_code
        == 200
    )
    history = s.api.get(
        "/api/v1/outcomes/ownership/history",
        headers=headers("finance"),
        params=dict(
            provider="azure",
            scope_id=SUB,
            resource_id=s.resource["resource_id"].lower(),
        ),
    ).json()["items"]
    assert [v["version"] for v in history] == [2, 1] and history[-1]["mapping"][
        "owner"
    ] == "team-platform"


def test_missing_billing_days_are_not_zero_filled(outcomes):
    s = outcomes
    day = import_daily(s, missing=True)
    r = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    )
    assert (
        r.status_code == 200
        and r.json()["items"] == []
        and r.json()["insufficient_baseline_groups"] == 1
    )


def test_future_planned_exception_is_exact_scoped_and_human_approved(outcomes):
    s = outcomes
    start = s.now[0].date() + timedelta(days=1)
    body = dict(
        provider="azure",
        scope_id=SUB,
        resource_id=s.resource["resource_id"],
        start=str(start),
        end=str(start + timedelta(days=2)),
        reason="Approved migration window with application owner",
        change_reference="CHG-PLANNED-42",
    )
    r = s.api.post("/api/v1/outcomes/suppressions", headers=headers(), json=body)
    assert r.status_code == 201, r.text
    s.now[0] += timedelta(days=4)
    day = import_daily(s)
    result = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    ).json()
    assert len(result["items"]) == 1 and result["items"][0]["state"] == "suppressed"
    assert (
        s.api.post(
            "/api/v1/outcomes/suppressions", headers=headers("finance"), json=body
        ).status_code
        == 403
    )


def test_case_version_conflicts_and_finance_role_cannot_change_infrastructure_reviews(
    outcomes,
):
    s = outcomes
    case = create_case(s)
    body = dict(
        version=case["version"],
        action="assign",
        owner="team-owner",
        note="Owner review for optimization",
    )
    assert (
        s.api.post(
            "/api/v1/outcomes/cases/" + case["id"] + "/actions",
            headers=headers("finance"),
            json=body,
        ).status_code
        == 403
    )
    act(s, case, "assign", owner="team-owner")
    assert (
        s.api.post(
            "/api/v1/outcomes/cases/" + case["id"] + "/actions",
            headers=headers(),
            json=body,
        ).status_code
        == 409
    )
    assert (
        s.api.get("/api/v1/outcomes/summary", headers=headers("viewer")).status_code
        == 403
    )


@pytest.fixture
def financial_postgres():
    privileged = os.getenv("CLOUDSAVER_TEST_PRIVILEGED_URL")
    if not privileged:
        pytest.skip("Use scripts/test_postgres.py for the financial database checks")
    name = "cloudsaver_outcomes_" + uuid4().hex

    def target(url):
        return urlunsplit(urlsplit(url)._replace(path="/" + name))

    with psycopg.connect(privileged, autocommit=True) as db:
        db.execute(
            sql.SQL("CREATE DATABASE {} OWNER cloudsaver_owner").format(
                sql.Identifier(name)
            )
        )
    try:
        owner = target(os.environ["CLOUDSAVER_TEST_OWNER_URL"])
        url = target(os.environ["CLOUDSAVER_TEST_APP_URL"])
        env = {**os.environ, "CLOUDSAVER_MIGRATION_URL": owner}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            check=True,
            capture_output=True,
        )
        yield url
    finally:
        from database.connection import dispose

        dispose()
        with psycopg.connect(privileged, autocommit=True) as db:
            db.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.mark.postgres
@pytest.mark.parametrize("outcomes", ["postgres"], indirect=True)
def test_financial_rls_append_only_and_concurrent_reconciliation(outcomes):
    from concurrent.futures import ThreadPoolExecutor
    from app.outcome_contracts import CaseAction
    from app.outcome_store import OutcomeConflict

    s = outcomes
    case = approve(s, create_case(s))
    post, *_ = prepare_proofs(s, case)
    case = act(s, case, "implement")
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    tenant = dict(s.tenant, user_id=UIDS["finance"], subject_type="user")
    body = CaseAction(
        version=case["version"],
        action="reconcile",
        note="Independent finance reconciliation",
    )

    def reconcile(_):
        try:
            return s.cases.act(tenant, case["id"], body, post)["state"]
        except OutcomeConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reconcile, range(2))) == [
            "conflict",
            "financially_reconciled",
        ]
    assert len(s.cases.detail(tenant, case["id"])["financial_claims"]) == 1
    tables = (
        "finops_ownership",
        "finops_anomalies",
        "finops_anomaly_events",
        "finops_suppressions",
        "savings_financial_claims",
    )
    for table in tables:
        with psycopg.connect(s.repo.url) as db:
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
        "DELETE FROM savings_financial_claims",
        "UPDATE savings_financial_claims SET amount=0",
        "UPDATE finops_ownership SET payload=payload",
        "DELETE FROM finops_anomaly_events",
        "DELETE FROM finops_suppressions",
    ):
        with psycopg.connect(s.repo.url) as db:
            db.execute("SELECT set_config('app.current_tenant_id',%s,true)", (TID,))
            with pytest.raises(errors.InsufficientPrivilege):
                db.execute(statement)
    owner = urlunsplit(
        urlsplit(os.environ["CLOUDSAVER_TEST_OWNER_URL"])._replace(
            path=urlsplit(s.repo.url).path
        )
    )
    rollback = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0021_billing_jobs"],
        env={**os.environ, "CLOUDSAVER_MIGRATION_URL": owner},
        capture_output=True,
        text=True,
    )
    assert rollback.returncode != 0 and "data-preserving rollback" in rollback.stderr
    with psycopg.connect(s.repo.url) as db:
        assert db.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE oid='savings_financial_claims'::regclass"
        ).fetchone()[0]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "coverage_complete",
            False,
            "COMPLETE_CURRENCY_AND_COMMITMENT_EVIDENCE_REQUIRED",
        ),
        (
            "commitments_accounted_for",
            False,
            "COMPLETE_CURRENCY_AND_COMMITMENT_EVIDENCE_REQUIRED",
        ),
        ("post_business_units", "0", "POSITIVE_BUSINESS_VOLUME_REQUIRED"),
        ("post_business_units", "13000", "DEMAND_CHANGE_EXCEEDS_COMPARABILITY_LIMIT"),
        (
            "provider_reconciled",
            False,
            "PROVIDER_RECONCILIATION_AND_CREDIT_ACCOUNTING_REQUIRED",
        ),
        (
            "ledger_digest",
            "a" * 64,
            "LOCAL_BILLING_LEDGER_MUST_MATCH_SIGNED_RECONCILIATION",
        ),
    ],
)
def test_incomplete_or_incomparable_evidence_cannot_book_benefit(
    outcomes, field, value, reason
):
    s = outcomes
    case = approve(s, create_case(s))
    post, bill, *_ = prepare_proofs(s, case)
    s.now[0] += timedelta(seconds=1)
    receipt(s, case, "billing", dict(bill, **{field: value}))
    case = act(s, case, "implement")
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    assert (
        reason in case["verification"]["reasons"]
        and case["verification"]["reconciled_financial_benefit"] is None
    )
    assert (
        s.cases.summary(s.tenant)["currencies"][0]["reconciled_financial_benefit"]
        is None
    )


def test_receipt_signature_tenant_and_idempotency_are_bound(outcomes):
    s = outcomes
    case = approve(s, create_case(s))
    _, _, _, audit = prepare_proofs(s, case)
    first, body, signature = receipt(s, case, "audit", audit)
    url = "/api/v1/outcomes/evidence/receipts"
    auth = {**headers("finance"), "X-Evidence-Signature": signature}
    retry = s.api.post(url, headers=auth, json=body)
    assert retry.status_code == 201 and retry.json() == dict(
        id=first["id"], cached=True
    )
    for altered in (
        dict(body, tenant_id=str(uuid4())),
        dict(body, scope_id=str(uuid4())),
        dict(body, payload=dict(audit, event_id="forged")),
    ):
        assert s.api.post(url, headers=auth, json=altered).status_code == 422
    changed = dict(body, payload=dict(audit, event_id="corrected"))
    signed = hmac.new(
        s.key.encode(),
        json.dumps(changed, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert (
        s.api.post(
            url,
            headers={**headers("finance"), "X-Evidence-Signature": signed},
            json=changed,
        ).status_code
        == 409
    )
    s.now[0] += timedelta(minutes=6)
    assert s.api.post(url, headers=auth, json=body).status_code == 422


def test_health_failure_and_partial_inventory_withhold_run_rate(outcomes):
    s = outcomes
    case = approve(s, create_case(s))
    post, _, health, _ = prepare_proofs(s, case)
    case = act(s, case, "implement")
    s.now[0] += timedelta(seconds=1)
    receipt(s, case, "slo", dict(health, health_accepted=False))
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    assert case["state"] == "implemented" and case["verification"]["reasons"] == [
        "ACCEPTED_POST_CHANGE_HEALTH_AND_UTILIZATION_REQUIRED"
    ]
    s.now[0] += timedelta(seconds=1)
    receipt(s, case, "slo", health)
    partial = dict(post, scan_id=str(uuid4()), scope_results=[])
    s.store.save(TID, partial, workspace=s.tenant)
    case = act(s, case, "validate", user="finance", scan_id=partial["scan_id"])
    assert case["verification"]["reasons"] == ["COMPLETE_SCOPE_OBSERVATION_REQUIRED"]


def test_investigation_correction_reopens_without_retroactive_suppression(outcomes):
    s = outcomes
    day = import_daily(s)
    item = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    ).json()["items"][0]
    url = "/api/v1/outcomes/anomalies/" + item["id"] + "/actions"

    def update(action, **fields):
        nonlocal item
        r = s.api.post(
            url,
            headers=headers("finance"),
            json=dict(
                version=item["version"],
                action=action,
                note="Finance review with application owner",
                **fields,
            ),
        )
        assert r.status_code == 200, r.text
        item = r.json()

    assert (
        s.api.post(
            url,
            headers=headers("finance"),
            json=dict(
                version=item["version"],
                action="resolve",
                resolution="actionable",
                note="Owner is still unknown",
            ),
        ).status_code
        == 409
    )
    update("assign", owner="team-qa")
    update("acknowledge")
    update("resolve", resolution="not_actionable")
    import_daily(s, source="late-additional-charges")
    corrected = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    ).json()["items"][0]
    assert (
        corrected["id"] == item["id"]
        and corrected["state"] == "open"
        and corrected["payload"]["increase"] == "140.00000000"
    )
    assert (
        s.api.post(
            "/api/v1/outcomes/suppressions",
            headers=headers(),
            json=dict(
                provider="azure",
                scope_id=SUB,
                resource_id=s.resource["resource_id"],
                start=str(day),
                end=str(day + timedelta(days=2)),
                reason="Cannot hide historical cost changes",
                change_reference="CHG-44",
            ),
        ).status_code
        == 422
    )
    assert (
        s.api.post(
            url,
            headers=headers("finance"),
            json=dict(
                version=item["version"],
                action="note",
                note="Stale decision must not overwrite correction",
            ),
        ).status_code
        == 409
    )


def test_corrected_billing_that_no_longer_triggers_requires_review(outcomes):
    s = outcomes
    day = import_daily(s)
    first = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    ).json()["items"][0]
    record = dict(
        x_ChargeId="late-credit",
        ProviderName="Azure",
        BillingAccountId=SUB,
        SubAccountId=SUB,
        BillingCurrency="USD",
        ChargePeriodStart=datetime.combine(day, time.min, timezone.utc),
        ChargePeriodEnd=datetime.combine(
            day + timedelta(days=1), time.min, timezone.utc
        ),
        ResourceId=s.resource["resource_id"],
        ChargeCategory="Credit",
        BilledCost="-70",
        EffectiveCost="-70",
    )
    FocusRepository(s.repo).import_records(
        s.tenant,
        ImportRequest(
            source_id="late-credit",
            provider="azure",
            sub_account_id=SUB,
            billing_currency="USD",
            period_start=day,
            period_end=day + timedelta(days=1),
            complete=False,
            records=[record],
        ),
    )
    next = s.api.post(
        "/api/v1/outcomes/anomalies/detect",
        headers=headers("finance"),
        json={"day": str(day)},
    ).json()["items"][0]
    assert (
        next["id"] == first["id"]
        and next["state"] == "review_required"
        and next["payload"]["signal_active"] is False
    )
    assert Decimal(next["payload"]["increase"]) == 0 and next["version"] == 2


def test_live_configuration_projection_proves_sizes_without_credentials(monkeypatch):
    from app.scanner import scan_inventory_observations, INVENTORY_QUERY

    row = dict(
        id=f"/subscriptions/{SUB}/resourceGroups/qa/providers/Microsoft.Compute/virtualMachines/live",
        name="live",
        type="microsoft.compute/virtualmachines",
        resourceGroup="qa",
        subscriptionId=SUB,
        location="eastus",
        vmSize="Standard_D2s_v5",
        skuName="Premium_LRS",
        skuTier="Premium",
        sizeGB=128,
        tags={"credential": "never-project"},
    )
    monkeypatch.setattr("app.scanner.execute_pages", lambda *args: [row])
    resource = scan_inventory_observations(None, [SUB])[0]
    projected = configuration(resource)
    assert projected == dict(
        vm_size="Standard_D2s_v5",
        sku_name="Premium_LRS",
        sku_tier="Premium",
        size_gb=128,
    )
    assert (
        "properties.hardwareProfile.vmSize" in INVENTORY_QUERY
        and "tags" not in projected
    )
    assert configuration(
        {
            "evidence": {
                "instance_class": "db.r6g.large",
                "volume_type": "gp3",
                "password": "never-project",
            }
        }
    ) == dict(instance_class="db.r6g.large", volume_type="gp3")


def test_financial_claim_preserves_all_bound_grants_and_health_corrections(
    outcomes, monkeypatch
):
    s = outcomes
    case = approve(s, create_case(s))
    post, _, health, _ = prepare_proofs(s, case)
    case = act(s, case, "implement")
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    case = act(s, case, "reconcile", user="finance", scan_id=post["scan_id"])
    monkeypatch.setenv(
        "CLOUDSAVER_EVIDENCE_SOURCES",
        json.dumps([dict(s.source, kinds=["audit", "billing"])]),
    )
    summary = s.cases.summary(s.tenant)["currencies"][0]
    assert (
        summary["reconciled_financial_benefit"] is None
        and summary["unsupported_financial_claims"] == 1
    )
    monkeypatch.setenv("CLOUDSAVER_EVIDENCE_SOURCES", json.dumps([s.source]))
    assert (
        s.cases.summary(s.tenant)["currencies"][0]["reconciled_financial_benefit"]
        == "3530.00000000"
    )
    s.now[0] += timedelta(seconds=1)
    receipt(s, case, "slo", dict(health, health_accepted=False))
    summary = s.cases.summary(s.tenant)["currencies"][0]
    assert (
        summary["validated_run_rate_reduction"] is None
        and summary["reconciled_financial_benefit"] is None
    )
    assert len(s.cases.detail(s.tenant, case["id"])["financial_claims"]) == 1


@pytest.mark.parametrize("reuse_provider_event", [False, True])
def test_one_action_or_billing_period_cannot_fund_two_cases(
    outcomes, reuse_provider_event
):
    s = outcomes
    first = approve(s, create_case(s))
    second = approve(s, create_case(s))
    event = str(uuid4())
    post, *_ = prepare_proofs(s, first, event_id=event)
    first = act(s, first, "implement")
    first = act(s, first, "validate", user="finance", scan_id=post["scan_id"])
    first = act(s, first, "reconcile", user="finance", scan_id=post["scan_id"])
    post, *_ = prepare_proofs(
        s, second, event_id=event if reuse_provider_event else str(uuid4())
    )
    if reuse_provider_event:
        r = s.api.post(
            "/api/v1/outcomes/cases/" + second["id"] + "/actions",
            headers=headers(),
            json=dict(
                version=second["version"],
                action="implement",
                note="Provider evidence cannot fund a second case",
            ),
        )
        assert r.status_code == 409 and "already bound" in r.json()["detail"]
    else:
        second = act(s, second, "implement")
        second = act(s, second, "validate", user="finance", scan_id=post["scan_id"])
        r = s.api.post(
            "/api/v1/outcomes/cases/" + second["id"] + "/actions",
            headers=headers("finance"),
            json=dict(
                version=second["version"],
                action="reconcile",
                scan_id=post["scan_id"],
                note="Overlapping periods cannot fund a second case",
            ),
        )
        assert r.status_code == 409 and "overlaps" in r.json()["detail"]
    assert (
        s.cases.summary(s.tenant)["currencies"][0]["reconciled_financial_benefit"]
        == "3530.00000000"
    )


def test_unknown_original_configuration_cannot_prove_a_rightsize(outcomes):
    s = outcomes
    s.resource["evidence"] = {}
    s.scan["scan_id"] = str(uuid4())
    s.store.save(TID, s.scan, workspace=s.tenant)
    case = approve(s, create_case(s))
    assert case["payload"]["configuration"] == {}
    post, *_ = prepare_proofs(s, case)
    case = act(s, case, "implement")
    case = act(s, case, "validate", user="finance", scan_id=post["scan_id"])
    assert case["state"] == "implemented" and case["verification"]["reasons"] == [
        "BASELINE_CONFIGURATION_REQUIRED"
    ]
    assert (
        s.cases.summary(s.tenant)["currencies"][0]["validated_run_rate_reduction"]
        is None
    )
