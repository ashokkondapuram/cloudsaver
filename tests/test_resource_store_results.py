"""AI result lookup must not miss older assessments behind unrelated attempts."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.inference_ledger import InferenceLedger
from app.resource_store import ResourceStore
from app.store import Store
from tests.support import stub_scanner

TID = '44444444-4444-4444-8444-444444444444'
SUB = '55555555-5555-4555-8555-555555555555'
KEY = 'test-resource-store-results-key-32chars'


def test_results_lookup_by_key_ignores_unrelated_recent_attempts(tmp_path):
    tenant = dict(
        tenant_id=TID,
        name='Results tenant',
        subscription_ids=[SUB],
        plan_tier='ENTERPRISE',
        api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
    )
    settings = Settings('azure', str(tmp_path / 'results.db'), (tenant,))
    scan = dict(
        scan_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        status='completed',
        mode='azure',
        subscriptions_scanned=1,
        total_items_found=1,
        total_monthly_waste_usd=None,
        findings=stub_scanner(tenant),
    )
    Store(settings.database).save(TID, scan, workspace=tenant)
    store = EnterpriseStore(settings)
    ledger = InferenceLedger(store)
    repo = ResourceStore(store)
    target_key = 'a' * 64
    other_key = 'b' * 64

    def invoke(key):
        return dict(
            advice=dict(
                summary=f'Assessment for {key[:8]}',
                risk_level='unknown',
                recommended_actions=[],
            ),
            evidence_digest='d' * 64,
            model='test',
            usage=dict(input_tokens=1, output_tokens=1),
        )

    meta = lambda resource_reference: dict(
        scan_id=scan['scan_id'],
        provider='azure',
        model='test-model',
        target_id='test',
        kind='resource_assessment',
        resource_reference=resource_reference,
    )

    for key in (other_key, target_key):
        ledger.run(
            tenant['tenant_id'],
            str(uuid4()),
            'f' * 64,
            10,
            lambda k=key: invoke(k),
            metadata=meta(key),
        )

    latest = repo.results(tenant['tenant_id'], keys={target_key})
    assert set(latest) == {target_key}
    assert latest[target_key]['summary'] == f'Assessment for {target_key[:8]}'
