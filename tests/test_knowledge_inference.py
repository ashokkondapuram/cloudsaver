import json

import httpx
import pytest

from app.ai_advisory import AIError, AIGateway, parse_advice
from app.identity_client import IdentityClient, reset_shared_client
from app.knowledge import confidence, retrieve
from tests.test_ai_advisory import advice, context, target, TID


def test_only_supplied_knowledge_publications_may_be_cited():
    ctx, _ = context()
    ctx['knowledge'] = [{'publication_id': 'approved-publication'}]
    output = dict(advice(), knowledge_citations=['approved-publication'])
    assert parse_advice(json.dumps(output), ctx)['knowledge_citations'] == ['approved-publication']
    for citations in (['fabricated'], ['approved-publication', 'approved-publication']):
        with pytest.raises(AIError):
            parse_advice(json.dumps(dict(output, knowledge_citations=citations)), ctx)


def test_retrieval_sends_only_taxonomy_and_no_client_data(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KNOWLEDGE_ENABLED', 'true')
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'items': []})
    reset_shared_client(IdentityClient('http://identity', 'offline-token', cache_seconds=0,
        transport=httpx.MockTransport(handle), subscribe=False))
    try:
        ctx, _ = context()
        ctx['resource_id'] = 'PRIVATE-RESOURCE-ID'
        ctx['tags'] = {'private-owner': 'PRIVATE-OWNER'}
        retrieve(ctx)
        assert len(requests) == 1
        assert set(requests[0].url.params) == {'provider', 'service_category', 'rule_ids'}
        assert 'PRIVATE' not in str(requests[0].url) and not requests[0].content
    finally:
        reset_shared_client(None)


def test_enabled_knowledge_failure_prevents_chargeable_inference(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_KNOWLEDGE_ENABLED', 'true')
    reset_shared_client(IdentityClient('http://identity', 'offline-token', cache_seconds=0,
        transport=httpx.MockTransport(lambda request: httpx.Response(503)), subscribe=False))
    class Budget:
        def run(self, *args, **kwargs):
            raise AssertionError('No budget claim or inference should occur after retrieval failure')
    try:
        ctx, assessment = context()
        gateway = AIGateway(enabled=True, targets=[target()], budget=Budget())
        with pytest.raises(AIError, match='no chargeable inference'):
            gateway.evaluate({'tenant_id': TID}, 'review', 'attempt', 'scan', ctx, assessment)
    finally:
        reset_shared_client(None)


def test_missing_or_stale_evidence_never_produces_high_confidence():
    for observation in ({'status': 'stale'}, {'status': 'unknown'}, {'status': 'recent'}):
        assert confidence({'observation': observation, 'evidence_gap_codes': ['missing']}) == 'INSUFFICIENT_EVIDENCE'
