"""Read-only retrieval sends taxonomy only; never send client resource identities or telemetry."""
import os


def retrieve(context):
    if os.getenv('CLOUDSAVER_KNOWLEDGE_ENABLED', '').lower() != 'true':
        return []
    from app.ai_advisory import AIError
    from app.identity_client import IdentityUnavailable, shared_client
    rule_ids = sorted({f['rule_id'] for f in context.get('findings', [])})
    if context.get('rule_id'):
        rule_ids.append(context['rule_id'])
    try:
        response = shared_client().get('/internal/v1/knowledge/retrieve', params={
            'provider': context['provider'], 'service_category': context['service_category'],
            'rule_ids': ','.join(rule_ids)}, timeout=3)
        if response.status_code != 200:
            raise AIError('Approved knowledge is unavailable; no chargeable inference was attempted.', 503)
        items = response.json()['items']
        if not isinstance(items, list) or len(items) > 5:
            raise ValueError()
        return items
    except AIError:
        raise
    except (IdentityUnavailable, RuntimeError, ValueError, KeyError, TypeError):
        raise AIError('Approved knowledge is unavailable; no chargeable inference was attempted.', 503) from None


def confidence(assessment):
    observation = assessment.get('observation') or {}
    if observation.get('status') != 'recent' or assessment.get('evidence_gap_codes'):
        return 'INSUFFICIENT_EVIDENCE'
    checks = [check for pillar in assessment.get('pillars', []) for check in pillar.get('checks', [])]
    observed = {check['code'] for check in checks if check['status'] != 'unknown'}
    if {'UTILIZATION_WINDOW', 'DEPENDENCY_GRAPH', 'BILLED_COST'} <= observed:
        # HIGH requires the new full telemetry contract, not the older 14-day Kubernetes summary.
        return 'MEDIUM'
    return 'LOW'


def validate_citations(advice, context):
    allowed = {item['publication_id'] for item in context.get('knowledge', [])}
    cited = advice.get('knowledge_citations', [])
    if len(cited) != len(set(cited)) or not set(cited) <= allowed:
        raise ValueError('Unsupported knowledge citation')
