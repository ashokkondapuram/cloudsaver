"""Real HTTP governance journey with synthetic loopback identity and signed test evidence only."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib, hmac, json, os, secrets, subprocess, sys, tempfile, time
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_postgres import docker
from scripts.test_real_stack import port
from tests.governance_http_fixture import user
from app.store import Store


def main():
    redis = "cloudsaver-gov-http-" + secrets.token_hex(6)
    processes = []
    logs = []
    with tempfile.TemporaryDirectory(prefix="cloudsaver-governance-") as temporary:
        try:
            docker(
                "run", "-d", "--name", redis, "-p", "127.0.0.1::6379", "redis:7-alpine"
            )
            info = json.loads(docker("inspect", redis))[0]
            redis_port = info["NetworkSettings"]["Ports"]["6379/tcp"][0]["HostPort"]
            tid, sub = str(uuid4()), str(uuid4())
            seed = secrets.token_hex(32)
            signing = secrets.token_hex(32)
            core, edge, web = port(), port(), port()
            path = str(Path(temporary) / "gov.db")
            tenant = dict(
                tenant_id=tid,
                name="HTTP Governance QA",
                plan_tier="ENTERPRISE",
                subscription_ids=[sub],
            )
            resource = dict(
                cloud_provider="azure",
                scope_id=sub,
                subscription_id=sub,
                resource_id=f"/subscriptions/{sub}/resourceGroups/qa/providers/Microsoft.Storage/storageAccounts/customer",
                resource_name="customer",
                resource_type="Microsoft.Storage/storageAccounts",
                evidence={"allow_blob_public_access": True},
            )
            scan = dict(
                scan_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                mode="azure",
                status="completed",
                total_items_found=1,
                subscriptions_scanned=1,
                total_monthly_waste_usd=None,
                cloud_providers=["azure"],
                inventory=[resource],
                findings=[],
                scope_results=[
                    dict(provider="azure", scope_id=sub, status="completed")
                ],
            )
            store = Store(path)
            store.save(tid, scan, workspace=tenant)
            env = os.environ.copy()
            env.update(
                CLOUDSAVER_ENVIRONMENT="development",
                CLOUDSAVER_AUTH_MODE="entra",
                CLOUDSAVER_KEY_VERIFIER="local",
                CLOUDSAVER_DIRECTORY_MODE="registry",
                CLOUDSAVER_TENANT_REGISTRY="env",
                CLOUDSAVER_DATABASE_URL="",
                CLOUDSAVER_DB=path,
                CLOUDSAVER_TENANTS=json.dumps([tenant]),
                CLOUDSAVER_AI_ENABLED="false",
                CLOUDSAVER_GITOPS_PUBLISH="false",
                CLOUDSAVER_HTTP_TEST_TOKEN=seed,
                CLOUDSAVER_HTTP_TEST_TENANT=tid,
                SCANNER_SERVICE_URL=f"http://127.0.0.1:{core}",
                API_GATEWAY_URL=f"http://127.0.0.1:{edge}",
                REDIS_URL=f"redis://127.0.0.1:{redis_port}/0",
                NEXT_TELEMETRY_DISABLED="1",
                CLOUDSAVER_GOVERNANCE_SOURCES=json.dumps(
                    [
                        dict(
                            tenant_id=tid,
                            source_id="http-collector",
                            providers=["azure"],
                            scope_ids=[sub],
                            kinds=["implementation", "verification"],
                            key_env="CLOUDSAVER_GOVERNANCE_KEY_PRIMARY",
                        )
                    ]
                ),
            )
            commands = [
                (
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "tests.governance_http_fixture:core",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(core),
                        "--no-access-log",
                    ],
                    ROOT,
                ),
                (
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "tests.governance_http_fixture:edge",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(edge),
                        "--no-access-log",
                    ],
                    ROOT,
                ),
                (
                    [
                        "node",
                        "node_modules/next/dist/bin/next",
                        "start",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        str(web),
                    ],
                    ROOT / "web-dashboard",
                ),
            ]
            for index, (command, cwd) in enumerate(commands):
                log = open(Path(temporary) / f"service-{index}.log", "w+")
                logs.append(log)
                processes.append(
                    subprocess.Popen(
                        command,
                        cwd=cwd,
                        env={
                            **env,
                            **(
                                {"CLOUDSAVER_GOVERNANCE_KEY_PRIMARY": signing}
                                if index == 0
                                else {}
                            ),
                        },
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                )
            with httpx.Client(timeout=15, trust_env=False) as client:
                for number, path in (
                    (core, "/healthz"),
                    (edge, "/healthz"),
                    (web, "/"),
                ):
                    end = time.monotonic() + 60
                    while True:
                        try:
                            if (
                                client.get(
                                    f"http://127.0.0.1:{number}" + path
                                ).status_code
                                == 200
                            ):
                                break
                        except httpx.HTTPError:
                            pass
                        if time.monotonic() > end or any(
                            p.poll() is not None for p in processes
                        ):
                            raise RuntimeError(
                                "Synthetic governance HTTP stack did not start"
                            )
                        time.sleep(0.2)
                root = f"http://127.0.0.1:{web}/api/v1/governance"

                def request(
                    method, path, actor="security", body=None, expected=200, extra=None
                ):
                    response = client.request(
                        method,
                        root + path,
                        headers={
                            "Authorization": "Bearer " + seed + ":" + actor,
                            **(extra or {}),
                        },
                        **({"json": body} if body is not None else {}),
                    )
                    assert response.status_code == expected, (
                        path,
                        response.status_code,
                        response.text,
                    )
                    return response.json()

                for name, role in [
                    ("admin", "ComplianceReviewer"),
                    ("owner", "ResourceOwner"),
                    ("security", "SecurityAnalyst"),
                    ("approver", "ChangeApprover"),
                    ("verifier", "ComplianceReviewer"),
                    ("business", "BusinessRiskOwner"),
                    ("auditor", "Auditor"),
                ]:
                    request(
                        "PUT",
                        "/access",
                        "admin",
                        dict(
                            subject_id=user(name),
                            alias=name,
                            role=role,
                            version=0,
                            expires_at=(
                                datetime.now(timezone.utc) + timedelta(days=30)
                            ).isoformat(),
                            maximum_score=25,
                            maximum_exception_days=7,
                            authority_reference="SYNTHETIC-HTTP-Authority",
                        ),
                    )
                request(
                    "POST",
                    "/controls",
                    "admin",
                    dict(
                        version=0,
                        owner=user("verifier"),
                        mandatory_obligation=True,
                        rationale="Synthetic policy used only in the isolated HTTP transport regression.",
                    ),
                    201,
                )
                context = dict(
                    application="payments",
                    environment="production",
                    classification="customer_data",
                    technical_owner=user("owner"),
                    business_owner=user("business"),
                    rationale="Synthetic owner confirmation of application and data classification.",
                )
                f = request(
                    "POST",
                    "/assessments",
                    body=dict(
                        scan_id=scan["scan_id"],
                        resource_id=resource["resource_id"],
                        context=context,
                    ),
                    expected=201,
                )["finding"]
                request(
                    "POST",
                    "/risks",
                    body=dict(
                        request_key=str(uuid4()),
                        finding_ids=[f["id"]],
                        business_owner=user("business"),
                        statement="Potential customer-data disclosure through public storage configuration.",
                        treatment_plan="Use an approved change and independently verify legitimate access.",
                        inherent_likelihood=4,
                        inherent_impact=5,
                        residual_likelihood=1,
                        residual_impact=4,
                        review_date=str(
                            (datetime.now(timezone.utc) + timedelta(days=20)).date()
                        ),
                    ),
                    expected=201,
                )
                f = request("GET", "/findings/" + f["id"])

                def act(action, actor="security", **fields):
                    nonlocal f
                    f = request(
                        "POST",
                        "/findings/" + f["id"] + "/actions",
                        actor,
                        dict(
                            version=f["version"],
                            action=action,
                            note="Synthetic reviewed decision through actual BFF gateway and core.",
                            **fields,
                        ),
                    )

                act("triage")
                act(
                    "propose",
                    "owner",
                    plan=dict(
                        change_reference="CHG-HTTP-42",
                        steps=[
                            "Set allowBlobPublicAccess to false on the exact account."
                        ],
                        dependency_checks=[
                            "Confirm authenticated application dependencies."
                        ],
                        validation_steps=[
                            "Read configuration and validate legitimate application access."
                        ],
                        rollback_plan="Rollback requires a separately reviewed and authorized change.",
                    ),
                )
                act("approve", "approver")

                def signed(kind, proof):
                    envelope = dict(
                        receipt_id=str(uuid4()),
                        tenant_id=tid,
                        finding_id=f["id"],
                        source_id="http-collector",
                        kind=kind,
                        issued_at=datetime.now(timezone.utc).isoformat(),
                        payload=proof,
                    )
                    signature = hmac.new(
                        signing.encode(),
                        json.dumps(
                            envelope, sort_keys=True, separators=(",", ":")
                        ).encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    return request(
                        "POST",
                        "/evidence/receipts",
                        "owner",
                        envelope,
                        201,
                        {"X-Evidence-Signature": signature},
                    )["id"]

                rid = signed(
                    "implementation",
                    dict(
                        plan_digest=f["payload"]["plan"]["digest"],
                        event_id="synthetic-http-fix",
                        operation="disable_blob_public_access",
                        status="Succeeded",
                        occurred_at=datetime.now(timezone.utc).isoformat(),
                    ),
                )
                act("implement", "owner", receipt_id=rid)
                resource = dict(resource, evidence={"allow_blob_public_access": False})
                post = dict(
                    scan,
                    scan_id=str(uuid4()),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    inventory=[resource],
                )
                store.save(tid, post, workspace=tenant)
                from app.governance_evidence import evaluate

                a = evaluate(
                    resource,
                    post,
                    context,
                    f["payload"]["control"],
                    datetime.now(timezone.utc),
                )
                rid = signed(
                    "verification",
                    dict(
                        plan_digest=f["payload"]["plan"]["digest"],
                        scan_id=post["scan_id"],
                        state_digest=a["state_digest"],
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        health_accepted=True,
                        legitimate_access_accepted=True,
                        validation_reference="SYNTHETIC-APP-ACCESS",
                    ),
                )
                act("verify", "verifier", receipt_id=rid, scan_id=post["scan_id"])
                act("close", scan_id=post["scan_id"])
                assert f["state"] == "closed"
                package = request("GET", "/findings/" + f["id"] + "/export", "auditor")
                assert (
                    package["technical_only"]
                    and package["content"]["authority_history"]
                    and package["content"]["finding"]["state"] == "closed"
                )
                request(
                    "POST",
                    "/findings/" + f["id"] + "/actions",
                    "auditor",
                    dict(
                        version=f["version"],
                        action="note",
                        note="An auditor must not mutate decision history.",
                    ),
                    403,
                )
                drift = dict(
                    post,
                    scan_id=str(uuid4()),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    inventory=[
                        dict(resource, evidence={"allow_blob_public_access": True})
                    ],
                )
                store.save(tid, drift, workspace=tenant)
                request("POST", "/monitor", body={})
                assert request("GET", "/findings/" + f["id"])["state"] == "reopened"
                assert client.get(root + "/findings").status_code == 401
                print(
                    "Real governance HTTP journey passed: observed issue, delegated human decisions, signed fix/health receipts, independent verification, closure, audit export and drift reopening; no cloud mutation or model call."
                )
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()
            docker("rm", "-f", redis)


if __name__ == "__main__":
    main()
