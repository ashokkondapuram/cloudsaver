from uuid import uuid4

import pytest

pytest_plugins = ['tests.test_enterprise']

from app.focus import FocusRepository
from app.resource_assessment import assessments
from app.scan_billing import materialize_scan_billing
from tests.test_enterprise import batch, charge, workspace
from tests.test_ai_advisory import SUB
from tests.test_v140 import NOW
from tests.test_lean_core import check
from tests.support import azure_disk_finding


def test_scan_materializes_billing_at_completion(evidence):
    _, store, _ = evidence
    repo = FocusRepository(store)
    tenant = workspace()
    disk = azure_disk_finding(SUB)
    end = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - __import__('datetime').timedelta(days=30)
    repo.import_records(
        tenant,
        __import__('app.focus', fromlist=['ImportRequest']).ImportRequest.model_validate(
            batch([charge(1, '11', ResourceId=disk['resource_id'], ChargePeriodStart=start.isoformat(), ChargePeriodEnd=(start + __import__('datetime').timedelta(days=1)).isoformat())],
                  source_id='scan-time', period_start=start.date().isoformat(), period_end=end.date().isoformat()),
        ),
    )
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=NOW.isoformat(),
        status='completed',
        mode='azure',
        cloud_providers=['azure'],
        subscriptions_scanned=1,
        total_items_found=1,
        findings=[],
        inventory=[dict(disk, evidence={'encrypted': True})],
    )
    saved = materialize_scan_billing(tenant, scan, repo)
    assert saved['billing_materialized'] is True
    assert saved['billing_window_start'] == start.date().isoformat()
    assessment = next(iter(assessments(saved, now=NOW).values()))[0]
    assert assessment['billed_cost_usd'] == 11
    assert check(assessment, 'BILLED_COST')['status'] == 'observed'
    # Re-attach must not replace scan-time billing with a live re-query (frozen snapshot).
    mutated = dict(saved)
    mutated['inventory'][0]['evidence']['billed_cost_usd'] = 11
    reloaded = repo.attach(tenant, mutated)
    assert reloaded is not mutated
    assert reloaded['inventory'][0]['evidence'].get('billed_cost_usd') == 11
