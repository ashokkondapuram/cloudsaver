from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.focus import FocusRepository, ImportRequest
from app.resource_assessment import planning_summary
from app.scan_billing import materialize_scan_billing
from app.scan_commitment_evidence import _distribute_charge, attach_commitment_evidence
from tests.test_enterprise import batch, charge, workspace

pytest_plugins = ['tests.test_enterprise']

WINDOW_END = datetime(2026, 11, 7, 0, 0, tzinfo=timezone.utc)
WINDOW_START = WINDOW_END - timedelta(days=30)


def test_distribute_charge_splits_across_hours():
    start = WINDOW_END - timedelta(days=1)
    end = WINDOW_END
    buckets: dict = {}
    assert _distribute_charge(start, end, Decimal("24"), buckets)
    assert len(buckets) == 24
    assert sum(buckets.values()) == Decimal("24")


class _EmptyStore:
    def transaction(self, _tenant_id):
        class _Tx:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def execute(self, *_args, **_kwargs):
                return self

            def fetchall(self):
                return []

        return _Tx()


def test_attach_skips_without_focus_rows():
    tenant_id = str(uuid4())
    store = _EmptyStore()
    tenant = {
        "tenant_id": tenant_id,
        "subscription_ids": [str(uuid4())],
        "aws_accounts": [],
        "gcp_projects": [],
        "allowed_providers": None,
    }
    scan = {
        "scan_id": str(uuid4()),
        "timestamp": WINDOW_END.isoformat(),
        "status": "completed",
        "findings": [{"estimated_savings_usd": "7300", "outcome": "condition_detected", "resource_id": "r1"}],
    }
    result = attach_commitment_evidence(tenant, dict(scan), store)
    assert "commitment_evidence" not in result


def _usage_window_focus_records():
    records = []
    for day in range(30):
        begin = WINDOW_START + timedelta(days=day)
        end = begin + timedelta(days=1)
        records.append(
            charge(
                day + 1,
                "24",
                ChargePeriodStart=begin.isoformat(),
                ChargePeriodEnd=end.isoformat(),
            )
        )
    return records


def test_attach_commitment_evidence_from_saved_focus(evidence):
    _, store, _ = evidence
    tenant = workspace()
    FocusRepository(store).import_records(
        tenant,
        ImportRequest.model_validate(
            batch(
                _usage_window_focus_records(),
                source_id="commitment-hourly",
                period_start=WINDOW_START.date().isoformat(),
                period_end=WINDOW_END.date().isoformat(),
            )
        ),
    )
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=WINDOW_END.isoformat(),
        status="completed",
        findings=[
            {
                "estimated_monthly_savings_usd": 7300,
                "outcome": "condition_detected",
                "resource_id": "r1",
            }
        ],
    )
    enriched = attach_commitment_evidence(tenant, dict(scan), store)
    evidence_block = enriched.get("commitment_evidence")
    assert evidence_block and evidence_block["source_verified"] is True
    assert len(evidence_block["usage_series"]["points"]) == 720
    assert evidence_block["cleanup_series"]["points"][0]["value"] == "10.0000"
    assert planning_summary(enriched)["status"] == "insufficient_evidence"


def test_materialize_attaches_commitment_when_cm_refresh_skipped(evidence, monkeypatch):
    _, store, _ = evidence
    repo = FocusRepository(store)
    tenant = workspace()
    repo.import_records(
        tenant,
        ImportRequest.model_validate(
            batch(
                _usage_window_focus_records(),
                source_id="commitment-hourly-skip-refresh",
                period_start=WINDOW_START.date().isoformat(),
                period_end=WINDOW_END.date().isoformat(),
            )
        ),
    )
    monkeypatch.setenv("CLOUDSAVER_SCAN_BILLING_REFRESH", "false")
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=WINDOW_END.isoformat(),
        status="completed",
        mode="azure",
        cloud_providers=["azure"],
        subscriptions_scanned=1,
        total_items_found=0,
        findings=[
            {
                "estimated_monthly_waste_usd": 730,
                "outcome": "condition_detected",
                "resource_id": "r1",
                "cloud_provider": "azure",
            }
        ],
        inventory=[],
    )
    saved = materialize_scan_billing(tenant, scan, repo)
    assert saved.get("commitment_evidence", {}).get("source_verified") is True
