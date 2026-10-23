"""Background processing of resource AI batches, one item at a time within the hourly budget."""
from datetime import timedelta
import logging
from uuid import NAMESPACE_URL, uuid5

from app.ai_advisory import AIError
from app.inference_ledger import attribution
from app.resource_assessment import group, merge
from app.resource_store import utcnow

log = logging.getLogger('cloudsaver.ai_batches')


def item_key(item):
    return str(uuid5(NAMESPACE_URL, f"cloudsaver:ai-batch:{item['batch_id']}:{item['resource_key']}"))


def reason_for(error):
    if error.status == 404:
        return 'target_unavailable'
    if error.status == 403:
        return 'policy_blocked'
    if error.status == 422:
        return 'context_too_large'
    if error.status == 502:
        return 'validation_failed'
    return 'provider_error'


def process_item(tenant, scans, repo, gateway, item):
    """Returns False when the batch must wait for the next budget hour."""
    tenant_id = tenant['tenant_id']
    scan = scans.get(tenant_id, item['scan_id'])
    findings = group(scan['findings']).get(item['resource_key']) if scan else None
    if not findings:
        repo.finish(tenant_id, item['id'], 'skipped', reason='resource_missing')
        return True
    assessment, context = merge(item['resource_key'], findings, observed_at=scan.get('timestamp'))
    if assessment['evidence_digest'] != item['evidence_digest']:
        repo.finish(tenant_id, item['id'], 'skipped', reason='evidence_changed')
        return True
    try:
        result = gateway.review(tenant, item['target_id'], item_key(item), item['scan_id'], context, assessment,
                                kind='resource_assessment', attribution=attribution(findings[0]))
    except AIError as error:
        if error.status == 429:
            now = utcnow()
            repo.wait_for_budget(tenant_id, item, now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            return False
        if error.status == 409:
            repo.finish(tenant_id, item['id'], 'uncertain', reason='outcome_uncertain')
        else:
            repo.finish(tenant_id, item['id'], 'failed', reason=reason_for(error))
        return True
    except Exception:
        log.exception('AI batch item failed')
        repo.finish(tenant_id, item['id'], 'uncertain', reason='outcome_uncertain')
        return True
    repo.finish(tenant_id, item['id'], 'completed', attempt_id=result['assessment_id'])
    return True


def process_batches(tenants, scans, repo, gateway, *, max_items=20):
    """Work through due batches for every workspace; returns the number of items attempted."""
    processed = 0
    for tenant in tenants:
        for batch_id in repo.due(tenant['tenant_id']):
            while processed < max_items:
                item = repo.claim(tenant['tenant_id'], batch_id)
                if item is None:
                    break
                processed += 1
                if not process_item(tenant, scans, repo, gateway, item):
                    break
            if processed >= max_items:
                return processed
    return processed
