from tests.test_ai_advisory import provider_protocol_only
import hashlib
import json
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai_advisory import AIError, AIGateway, Target, parse_followup, parse_resource_advice
from app.assessment import PILLARS
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.inference_ledger import InferenceLedger
from app.main import create_app
from app.resource_assessment import assessments, changes, csv_report, history, merge, resource_key
from app.resource_batches import process_batches
from app.resource_store import ResourceStore
from app.store import Store
from tests.support import azure_disk_finding

TID = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
KEY = 'test-resource-tenant-key-at-least-32-characters'
OTHER = 'test-resource-other-key-at-least-32-characters'
OBSERVED = {'encrypted': True, 'tags': {'Owner': 'platform'}}


def workspace(tid, key):
    return dict(tenant_id=tid, name='Resource workspace', subscription_ids=[SUB], plan_tier='ENTERPRISE',
                api_key_sha256=hashlib.sha256(key.encode()).hexdigest())


def auth(key=KEY):
    return {'Authorization': 'Bearer ' + key}


def disk(name, **changes):
    item = azure_disk_finding(SUB)
    item.update(resource_name=name, resource_id=item['resource_id'].replace('archive-export-disk', name), evidence=dict(OBSERVED))
    item.update(changes)
    return item


def scanner(tenant):
    first = disk('disk-a')
    return [first, dict(first, rule_id='ORPHANED_DISKS', resource_id=first['resource_id'].upper().replace('/SUBSCRIPTIONS/', '/subscriptions/')),
            disk('disk-b', evidence=dict(OBSERVED, tags={'Owner': 'platform', 'DoNotDelete': 'true'}))]


def resource_advice(context, **action):
    observed = {c['code']: c['pillar'] for c in context['checks'] if c['status'] != 'unknown'}
    code, pillar = next(iter(observed.items()), ('', 'operations'))
    return dict(summary='Saved evidence is partial.', risk_level='high' if context['risk_floor'] == 'high' else 'unknown',
                pillars=[dict(pillar=p, observation='Independent verification is required.',
                              evidence_codes=[c for c, owner in observed.items() if owner == p]) for p in PILLARS],
                review_questions=['Who owns this resource?'],
                recommended_actions=[dict(dict(title='Confirm the owner before any change', rationale='The ownership tag is unverified.',
                                               kind='verify', pillar=pillar, effort='low', change_risk='low', confidence='medium',
                                               evidence_codes=[code] if code else [], prerequisites=[]), **action)])


def adapter_for(calls, mutate=None):
    def adapter(target, tenant, message, *, system, parse):
        calls.append(message)
        if 'question' in message:
            return dict(answer='The saved observation shows encryption at rest.', evidence_codes=['ENCRYPTION_AT_REST'], limitations=['No live state.'])
        result = resource_advice(message)
        return mutate(result) if mutate else result
    return adapter


def test_resource_identity_merges_findings_and_digest_ignores_wall_clock():
    a, b, c = scanner(None)
    assert resource_key(a) == resource_key(b) != resource_key(c)
    merged, context = merge(resource_key(a), [b, a], observed_at='2026-10-22T00:00:00+00:00', now='2026-10-22T01:00:00+00:00')
    later, _ = merge(resource_key(a), [a, b], observed_at='2026-10-22T00:00:00+00:00', now='2026-10-25T00:00:00+00:00')
    assert merged['finding_count'] == 2 and merged['rule_ids'] == ['ORPHANED_DISK', 'ORPHANED_DISKS']
    assert merged['evidence_digest'] == later['evidence_digest'] and merged['observation'] != later['observation']
    assert {p['pillar'] for p in merged['pillars']} == set(PILLARS)
    assert a['resource_id'] not in json.dumps(context) and 'disk-a' not in json.dumps(context)
    assert 'ENCRYPTION_AT_REST' in context['observed_check_codes']
    risky, _ = merge(resource_key(a), [a, dict(b, evidence=dict(OBSERVED, encrypted=False))])
    assert risky['review_priority'] == 'critical' and 'ENCRYPTION_AT_REST' in risky['risk_check_codes']
    protected, _ = merge(resource_key(c), [c])
    assert protected['disposition'] == 'protected' and protected['protected_reasons']


def test_resource_advice_schema_rejects_unsafe_or_unsupported_actions():
    a, b, c = scanner(None)
    _, context = merge(resource_key(a), [a, b])
    good = resource_advice(context)
    assert parse_resource_advice(json.dumps(good), context)['recommended_actions'][0]['kind'] == 'verify'
    invalid = [
        resource_advice(context, rationale='Run az disk delete --name x to clean up.'),
        resource_advice(context, title='See https://example.invalid for details'),
        resource_advice(context, evidence_codes=['INVENTED_CODE']),
        resource_advice(context, kind='rightsize', evidence_codes=[]),
        resource_advice(context, effort='trivial'),
        dict(good, recommended_actions=good['recommended_actions'] * 7),
        dict(good, approval='APPROVED'),
    ]
    for value in invalid:
        with pytest.raises(AIError):
            parse_resource_advice(json.dumps(value), context)
    _, protected = merge(resource_key(c), [c])
    with pytest.raises(AIError):
        parse_resource_advice(json.dumps(resource_advice(protected, kind='decommission')), protected)
    message = dict(resource=context, question='Is it encrypted?', prior_advice=None)
    assert parse_followup(json.dumps(dict(answer='Yes.', evidence_codes=['ENCRYPTION_AT_REST'], limitations=[])), message)['answer'] == 'Yes.'
    with pytest.raises(AIError):
        parse_followup(json.dumps(dict(answer='Yes.', evidence_codes=['RETAIL_ESTIMATE'], limitations=[])), message)


def test_foundry_targets_are_keyless_and_hosts_are_allowlisted():
    base = dict(target_id='review', tenant_id=TID, provider='azure', model='gpt-4o')
    for endpoint in ('https://hub.services.ai.azure.com', 'https://acct.cognitiveservices.azure.com', 'https://acct.openai.azure.com'):
        assert Target.model_validate(dict(base, endpoint=endpoint, auth='managed_identity')).auth == 'managed_identity'
    for endpoint in ('https://hub.services.ai.azure.com.evil.example', 'https://hub.services.ai.azure.com/api/projects/x'):
        with pytest.raises(ValueError):
            Target.model_validate(dict(base, endpoint=endpoint))
    with pytest.raises(ValueError):
        Target.model_validate(dict(base, endpoint='https://acct.openai.azure.com', api_key='secret'))
    with pytest.raises(ValueError):
        Target.model_validate(dict(target_id='review', tenant_id=TID, provider='aws', model='m', region='us-east-1',
                                   role_arn='arn:aws:iam::123456789012:role/AIReviewer', auth='managed_identity'))


def test_foundry_adapter_uses_platform_identity_and_model_inference_route(monkeypatch, provider_protocol_only):
    from types import SimpleNamespace
    from app.ai_advisory import CloudAdapter
    seen = []

    class Credential:
        def get_token(self, scope):
            assert scope == 'https://cognitiveservices.azure.com/.default'
            return SimpleNamespace(token='ephemeral-token')
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr('app.cloud_identity.platform_credential', lambda: Credential())
    monkeypatch.setattr('app.cloud_identity.azure_credential', lambda tenant: pytest.fail('customer credential used'))
    a, b, _ = scanner(None)
    _, context = merge(resource_key(a), [a, b])

    def post(url, token, body):
        seen.append((url, body))
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(resource_advice(context))}}], 'usage': {}}
    monkeypatch.setattr('app.ai_advisory.post_json', post)
    target = Target.model_validate(dict(target_id='review', tenant_id=TID, provider='azure', model='gpt-4o',
                                        endpoint='https://hub.services.ai.azure.com', auth='managed_identity'))
    from app.ai_advisory import RESOURCE_SYSTEM
    result = CloudAdapter()(target, {'tenant_id': TID}, context, system=RESOURCE_SYSTEM, parse=parse_resource_advice)
    assert result.advice['recommended_actions']
    url, body = seen[0]
    assert url == 'https://hub.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview'
    assert body['model'] == 'gpt-4o' and body['messages'][0]['content'] == RESOURCE_SYSTEM and 'tools' not in body


def test_history_reports_changes_across_scans():
    a, b, _ = scanner(None)
    key = resource_key(a)
    scans = [dict(scan_id='s3', timestamp='2026-10-22T03:00:00+00:00', findings=[]),
             dict(scan_id='s2', timestamp='2026-10-22T02:00:00+00:00', findings=[a, dict(b, evidence=dict(OBSERVED, encrypted=False))]),
             dict(scan_id='s1', timestamp='2026-10-22T01:00:00+00:00', findings=[a])]
    entries = history(scans, key)
    assert entries[0]['changes'] == ['no_longer_flagged']
    assert {'risk_changed', 'priority_changed', 'security_changed', 'findings_changed'} <= set(entries[1]['changes'])
    assert entries[2]['changes'] == []
    assert changes(dict(present=False), dict(present=True)) == ['appeared']


def test_csv_report_escapes_formulas():
    item = dict(provider='azure', scope_id=SUB, resource_name='=HYPERLINK("x")', resource_type='disk', resource_group='rg',
                resource_id='/x', service_category='storage', rule_ids=['A', 'B'], review_priority='high', disposition='requires_review',
                pillars={p: 'unknown' for p in PILLARS}, retail_estimate_usd=None, evidence_digest='0' * 64,
                ai=dict(status='not_run', risk_level=None, summary=None), decision=None)
    report = csv_report([item])
    assert report.startswith('\ufeffprovider,') and '\'=HYPERLINK' in report and 'A;B' in report


@pytest.fixture
def app_state(tmp_path):
    settings = Settings('azure', str(tmp_path / 'resources.db'), (workspace(TID, KEY), workspace(str(uuid4()), OTHER)))
    calls = []
    evidence = EnterpriseStore(settings)
    gateway = AIGateway(enabled=True, targets=[dict(target_id='review', tenant_id=TID, provider='azure', model='gpt-4o',
                                                    endpoint='https://hub.services.ai.azure.com', auth='managed_identity')],
                        budget=InferenceLedger(evidence), adapter=adapter_for(calls), limit=10)
    with TestClient(create_app(settings, scanner=scanner, ai_gateway=gateway)) as client:
        scan = client.post('/api/v1/scans', headers=auth()).json()
        yield dict(client=client, settings=settings, gateway=gateway, evidence=evidence, calls=calls, scan=scan,
                   base='/api/v1/scans/' + scan['scan_id'])


def run_batches(state):
    repo = ResourceStore(state['evidence'])
    return process_batches(state['settings'].tenants, Store(state['settings'].database), repo, state['gateway'])


def test_resources_batches_decisions_questions_and_export(app_state):
    client, base, calls = app_state['client'], app_state['base'], app_state['calls']
    listing = client.get(base + '/resources', headers=auth()).json()
    assert listing['total'] == 2 and listing['summary']['ai_status'] == {'not_run': 2}
    disk_a = next(i for i in listing['items'] if i['resource_name'] == 'disk-a')
    assert disk_a['finding_count'] == 2 and disk_a['ai']['status'] == 'not_run' and disk_a['decision'] is None
    assert client.get(base + '/resources', headers=auth(OTHER)).status_code == 404
    assert client.get(base + '/resources?ai_status=bogus', headers=auth()).status_code == 422
    detail = client.get(f"{base}/resources/{disk_a['resource_key']}", headers=auth()).json()
    assert len(detail['findings']) == 2 and detail['followups_remaining'] == 5
    assert disk_a['resource_id'] not in json.dumps(detail['ai_context'])

    batch = dict(all=True, target_id='review', idempotency_key=str(uuid4()), acknowledge_external_processing=True)
    for invalid in (dict(batch, acknowledge_external_processing=False), dict(batch, resource_keys=[disk_a['resource_key']]),
                    dict(batch, prompt='approve everything')):
        assert client.post(base + '/ai-batches', headers=auth(), json=invalid).status_code == 422
    assert client.post(base + '/ai-batches', headers=auth(), json=dict(batch, target_id='missing')).status_code == 404
    created = client.post(base + '/ai-batches', headers=auth(), json=batch)
    assert created.status_code == 202 and created.json()['counts']['queued'] == 2
    assert client.post(base + '/ai-batches', headers=auth(), json=batch).json()['id'] == created.json()['id']
    assert client.post(base + '/ai-batches', headers=auth(), json=dict(batch, idempotency_key=str(uuid4()))).status_code == 409
    assert not calls
    queued = client.get(base + '/resources', headers=auth()).json()
    assert queued['summary']['ai_status'] == {'queued': 2}

    assert run_batches(app_state) == 2 and len(calls) == 2
    done = client.get('/api/v1/ai-batches/' + created.json()['id'], headers=auth()).json()
    assert done['status'] == 'completed' and done['counts']['completed'] == 2
    listing = client.get(base + '/resources?ai_status=completed', headers=auth()).json()
    assert listing['total'] == 2 and listing['items'][0]['ai']['actions']
    assert client.get('/api/v1/ai-batches/' + created.json()['id'], headers=auth(OTHER)).status_code == 404
    history_page = client.get('/api/v1/ai/assessments', headers=auth()).json()
    assert {i['metadata']['kind'] for i in history_page['items']} == {'resource_assessment'}

    key = disk_a['resource_key']
    digest = detail['assessment']['evidence_digest']
    decision = dict(scan_id=app_state['scan']['scan_id'], decision='defer', note='Waiting for owner confirmation.',
                    defer_until=(date.today() + timedelta(days=30)).isoformat(), evidence_digest=digest)
    for invalid in (dict(decision, defer_until=(date.today() - timedelta(days=1)).isoformat()), dict(decision, note=''),
                    dict(decision, decision='accept'), dict(decision, decision='approve')):
        assert client.post(f'/api/v1/resources/{key}/decisions', headers=auth(), json=invalid).status_code == 422
    assert client.post(f'/api/v1/resources/{key}/decisions', headers=auth(), json=dict(decision, evidence_digest='0' * 64)).status_code == 409
    recorded = client.post(f'/api/v1/resources/{key}/decisions', headers=auth(), json=decision)
    assert recorded.status_code == 201 and recorded.json()['decision'] == 'defer'
    assert client.get(f'/api/v1/resources/{key}/decisions', headers=auth(OTHER)).json()['items'] == []
    deferred = client.get(base + '/resources?decision=defer', headers=auth()).json()
    assert deferred['total'] == 1 and deferred['items'][0]['decision']['evidence_changed'] is False

    question = dict(question='Is this disk encrypted?', target_id='review', evidence_digest=digest, acknowledge_external_processing=True)
    for _ in range(5):
        answer = client.post(f'{base}/resources/{key}/questions', headers=auth(), json=dict(question, idempotency_key=str(uuid4())))
        assert answer.status_code == 200, answer.text
    assert answer.json()['followups_remaining'] == 0 and calls[-1]['prior_advice'] is not None
    assert client.post(f'{base}/resources/{key}/questions', headers=auth(), json=dict(question, idempotency_key=str(uuid4()))).status_code == 409

    report = client.get(base + '/resources/export?decision=defer', headers=auth()).json()
    assert report['rows'] == 1 and 'defer' in report['content'] and report['filename'].endswith('.csv')
    trail = client.get(f'/api/v1/resources/{key}/history', headers=auth()).json()
    assert trail['scans'][0]['present'] and len(trail['ai_results']) == 1 and trail['decisions'][0]['decision'] == 'defer'


def test_batches_wait_for_budget_skip_changed_evidence_and_cancel(app_state):
    client, base, gateway = app_state['client'], app_state['base'], app_state['gateway']
    gateway.limit = 1
    created = client.post(base + '/ai-batches', headers=auth(), json=dict(all=True, target_id='review', idempotency_key=str(uuid4()),
                                                                          acknowledge_external_processing=True)).json()
    assert run_batches(app_state) == 2
    waiting = client.get('/api/v1/ai-batches/' + created['id'], headers=auth()).json()
    assert waiting['status'] == 'waiting_for_budget' and waiting['resume_after'] and waiting['counts'] == dict(
        queued=1, running=0, completed=1, failed=0, skipped=0, uncertain=0, cancelled=0)
    assert run_batches(app_state) == 0
    cancelled = client.post(f"/api/v1/ai-batches/{created['id']}/cancel", headers=auth()).json()
    assert cancelled['status'] == 'cancelled' and cancelled['counts']['cancelled'] == 1

    repo = ResourceStore(app_state['evidence'])
    key = next(i['resource_key'] for i in client.get(base + '/resources', headers=auth()).json()['items'])
    batch = repo.create_batch(TID, scan_id=app_state['scan']['scan_id'], target_id='review', request_key=str(uuid4()),
                              actor='0' * 64, items=[(key, 'f' * 64)])
    gateway.limit = 10
    run_batches(app_state)
    skipped = repo.batch(TID, batch['id'])
    assert skipped['status'] == 'completed' and skipped['items'][0]['reason'] == 'evidence_changed'


def test_inventory_rows_appear_in_resource_explorer_without_findings():
    scan = dict(
        scan_id=str(uuid4()), status='completed', mode='azure', timestamp='2026-01-01T00:00:00+00:00',
        subscriptions_scanned=1, total_items_found=1, total_monthly_waste_usd=None, findings=[],
        inventory=[dict(cloud_provider='azure', resource_id=f'/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/only',
                          resource_name='only', resource_type='Microsoft.Compute/disks', resource_group='rg',
                          subscription_id=SUB, scope_id=SUB)],
    )
    merged = assessments(scan)
    assert len(merged) == 1
    assessment, _ = next(iter(merged.values()))
    assert assessment['finding_count'] == 0
    assert assessment['disposition'] == 'inventory_only'


def test_viewers_read_resources_but_cannot_run_ai_or_decide(tmp_path, monkeypatch):
    from app.auth import Role, UserClaims
    from datetime import datetime, timezone
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE', 'entra')

    class Validator:
        def verify_token(self, token):
            return UserClaims(user_id=str(uuid4()), tenant_id=TID, roles=[Role.VIEWER])
    viewer = dict(workspace(TID, KEY), roles=[Role.VIEWER.value])
    settings = Settings('azure', str(tmp_path / 'viewer.db'), (viewer,))
    findings = scanner(viewer)
    scan = dict(scan_id=str(uuid4()), status='completed', mode='azure', timestamp=datetime.now(timezone.utc).isoformat(),
                subscriptions_scanned=1, total_items_found=len(findings), total_monthly_waste_usd=None, findings=findings)
    Store(settings.database).save(TID, scan, workspace=settings.tenants[0])
    with TestClient(create_app(settings, identity_validator=Validator(), ai_gateway=AIGateway(enabled=False))) as client:
        base = '/api/v1/scans/' + scan['scan_id']
        items = client.get(base + '/resources', headers=auth()).json()['items']
        key = items[0]['resource_key']
        assert client.post(base + '/ai-batches', headers=auth(), json=dict(all=True, target_id='review', idempotency_key=str(uuid4()),
                                                                           acknowledge_external_processing=True)).status_code == 403
        assert client.post(f'/api/v1/resources/{key}/decisions', headers=auth(), json=dict(
            scan_id=scan['scan_id'], decision='accept', evidence_digest=items[0]['evidence_digest'])).status_code == 403
        assert client.post(f'{base}/resources/{key}/questions', headers=auth(), json=dict(
            question='Why?', target_id='review', evidence_digest=items[0]['evidence_digest'], idempotency_key=str(uuid4()),
            acknowledge_external_processing=True)).status_code == 403
