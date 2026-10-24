import copy
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai_advisory import AIGateway, AIError, Target
from app.config import Settings
from app.foundry_config import normalize, provider_fields
from app.inference_ledger import InferenceLedger
from app.tenant_config import normalize_tenant
from app.tenant_registry import MemoryRegistry
from tests.test_ai_advisory import target, TID, context, advice
from tests.test_enterprise import evidence, metadata, result, workspace
DEFAULT_POLICY = json.loads((Path(__file__).resolve().parents[1] / 'platform/contracts/fixtures/ai-policy-v1.json').read_text())['policy']


@pytest.fixture
def foundry(evidence, monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_DIRECTORY_MODE', 'registry')
    settings, store, scan = evidence
    registry = MemoryRegistry((normalize_tenant(workspace()),))
    settings = Settings('azure', settings.database, registry.bootstrap, None, registry)
    ledger = InferenceLedger(store)
    gateway = AIGateway(targets=[target(region='eastus')], enabled=True, budget=ledger, settings=settings,
                        adapter=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('No live inference in governance tests')))
    policy = copy.deepcopy(DEFAULT_POLICY)
    policy.update(enabled=True, max_input_tokens_per_request=16000)
    policy['allowed_models']['azure'] = ['operator-model']
    policy['allowed_regions']['azure'] = ['eastus']
    gateway.foundry.policy_reader = lambda: {'version': 1, 'policy': policy}
    tenant = dict(registry.get(TID), roles=['TenantAdmin'])
    config = normalize(None)
    config['providers']['azure'].update(enabled=True, target_id='review', **provider_fields(gateway.targets[0], TID))
    config['policy']['advisory_enabled'] = True
    return gateway, tenant, config, policy, scan


def test_settings_save_is_versioned_and_independently_consented(foundry):
    gateway, tenant, config, _, _ = foundry
    controller = gateway.foundry
    with pytest.raises(AIError, match='Acknowledge'):
        controller.save(tenant, 1, config, False)
    saved = controller.save(tenant, 1, config, True)
    assert saved['version'] == 2
    assert saved['ai_foundry']['policy']['allow_anonymized_knowledge_candidates'] is False
    with pytest.raises(AIError) as stale:
        controller.save(tenant, 1, config, True)
    assert stale.value.status == 409
    assert controller.settings.registry.audit[-1][2] == 'ai_settings_updated'


def test_saved_preferences_drive_real_gateway_budget_reservations_and_metering(foundry):
    from app.ai_advisory import InferenceResult
    gateway, tenant, config, _, scan = foundry
    config['policy']['max_input_tokens_per_request'] = 16000
    gateway.foundry.save(tenant, 1, config, True)
    calls = []
    def adapter(target, principal, message):
        calls.append((target, message))
        return InferenceResult(advice(), {'input_tokens': 100, 'output_tokens': 20, 'billed_cost_usd': None})
    gateway.adapter = adapter
    ctx, assessment = context()
    response = gateway.evaluate(tenant, 'review', uuid4(), scan['scan_id'], ctx, assessment)
    assert response['usage']['input_tokens'] == 100 and len(calls) == 1
    assert calls[0][0].max_input_tokens == 4000  # The approved target ceiling can narrow the workspace ceiling.
    assert calls[0][0].max_output_tokens == 1200
    assert gateway.budget.window_summary(TID)['monthly_tokens_used_or_reserved'] == 120
    record = gateway.budget.page(TID)['items'][0]
    assert record['metadata']['reserved_tokens'] == 5200
    assert record['status'] == 'completed'


def test_foundry_preferences_and_validations_are_exposed_through_the_scanner_api(foundry, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.test_enterprise import AUTH
    monkeypatch.setenv('CLOUDSAVER_KEY_VERIFIER', 'local')
    monkeypatch.setenv('CLOUDSAVER_AUTH_MODE', 'workspace')
    gateway, tenant, config, _, _ = foundry
    with TestClient(create_app(gateway.foundry.settings, ai_gateway=gateway)) as api:
        view = api.get('/api/v1/settings/ai', headers=AUTH)
        assert view.status_code == 200 and view.json()['version'] == 1
        assert view.json()['usage']['attempts_last_30d'] == 0
        body = dict(version=1, ai_foundry=config, acknowledge_external_processing=True)
        saved = api.put('/api/v1/settings/ai', headers=AUTH, json=body)
        assert saved.status_code == 200 and saved.json()['version'] == 2
        assert api.put('/api/v1/settings/ai', headers=AUTH, json=body).status_code == 409
        assert api.get('/api/v1/settings/ai').status_code == 401
        body['ai_foundry']['providers']['azure']['api_key'] = 'not-a-supported-setting'
        assert api.put('/api/v1/settings/ai', headers=AUTH, json=body).status_code == 422


@pytest.mark.parametrize('change', [{'roles': ['Viewer']}, {'scope_restrictions': {'azure': ['scope']}}, {'all_providers': False}])
def test_scoped_or_viewer_keys_cannot_configure_workspace_ai(foundry, change):
    gateway, tenant, config, _, _ = foundry
    with pytest.raises(AIError) as denied:
        gateway.foundry.save(dict(tenant, **change), 1, config, True)
    assert denied.value.status == 403


def test_directory_cutover_and_plan_downgrade_fail_closed(foundry, monkeypatch):
    gateway, tenant, config, _, _ = foundry
    monkeypatch.setenv('CLOUDSAVER_DIRECTORY_MODE', 'cutover')
    with pytest.raises(AIError, match='locked'):
        gateway.foundry.save(tenant, 1, config, True)
    monkeypatch.setenv('CLOUDSAVER_DIRECTORY_MODE', 'registry')
    with pytest.raises(AIError, match='plan'):
        gateway.foundry.save(dict(tenant, plan_tier='STARTER'), 1, config, True)


def test_endpoint_region_role_or_guardrail_cannot_escape_operator_binding(foundry):
    gateway, tenant, config, _, _ = foundry
    for key, value in [('endpoint_url', 'https://other.openai.azure.com'), ('region', 'unapproved'), ('deployment_name', 'different')]:
        changed = copy.deepcopy(config)
        changed['providers']['azure'][key] = value
        with pytest.raises(AIError):
            gateway.foundry.validate_configuration(tenant, changed)
    config['providers']['azure']['api_key'] = 'never-store-this'
    with pytest.raises(ValidationError):
        gateway.foundry.validate_configuration(tenant, config)


def test_current_kill_switch_and_source_affinity_are_rechecked_before_provider_call(foundry):
    gateway, tenant, config, policy, _ = foundry
    gateway.foundry.save(tenant, 1, config, True)
    assert gateway.available(tenant)['targets'][0]['allowed_source_providers'] == ['azure']
    with pytest.raises(AIError, match='same-cloud'):
        gateway._selection(tenant, 'review', 'aws')
    with pytest.raises(AIError, match='hosting-cloud'):
        gateway._selection(tenant, 'review', 'kubernetes')
    policy['disabled_providers'] = ['azure']
    assert gateway.available(tenant)['targets'] == []
    ctx, assessment = context()
    with pytest.raises(AIError, match='disabled'):
        gateway.evaluate(tenant, 'review', uuid4(), 'scan', ctx, assessment)


def test_cross_provider_route_cannot_substitute_key_ack_for_human_step_up(foundry):
    gateway, tenant, config, policy, _ = foundry
    config['policy']['routing_mode'] = 'workspace_default_provider'
    policy['allow_cross_provider'] = True
    with pytest.raises(AIError, match='step-up'):
        gateway.foundry.save(tenant, 1, config, True)


def test_bedrock_profile_cannot_route_to_a_region_outside_operator_policy(monkeypatch):
    from app.ai_advisory import CloudAdapter
    calls = []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get_inference_profile(self, **kwargs):
            return {'status': 'ACTIVE', 'models': [{'modelArn': 'arn:aws:bedrock:eu-west-1::foundation-model/example-model'}]}
    class Session:
        def client(self, name, **kwargs):
            calls.append(name)
            assert name == 'bedrock', 'Runtime invocation must be blocked before a paid call.'
            return Client()
    monkeypatch.setattr('app.cloud_identity.aws_session', lambda source: Session())
    selected = Target.model_validate(dict(target('aws', approved_regions=['us-east-1']), model='us.example-profile'))
    ctx, _ = context()
    with pytest.raises(AIError, match='approved destination'):
        CloudAdapter()(selected, {'tenant_id': TID}, ctx)
    assert calls == ['bedrock']


def test_bedrock_converse_attaches_the_approved_published_guardrail(monkeypatch):
    from app.ai_advisory import CloudAdapter
    observed = []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def converse(self, **kwargs):
            observed.append(kwargs)
            return {'stopReason': 'end_turn', 'output': {'message': {'content': [{'text': json.dumps(advice())}]}},
                    'usage': {'inputTokens': 10, 'outputTokens': 10}}
    class Session:
        def client(self, name, **kwargs):
            assert name == 'bedrock-runtime'
            return Client()
    monkeypatch.setattr('app.cloud_identity.aws_session', lambda source: Session())
    selected = Target.model_validate(target('aws', guardrail_id='approved123', guardrail_version='1'))
    ctx, _ = context()
    CloudAdapter()(selected, {'tenant_id': TID}, ctx)
    assert observed[0]['guardrailConfig'] == {'guardrailIdentifier': 'approved123', 'guardrailVersion': '1'}


def test_diagnostics_are_durable_rate_limited_and_never_claim_inference_rbac(foundry):
    gateway, tenant, config, _, _ = foundry
    gateway.foundry.save(tenant, 1, config, True)
    calls = []
    def probe(target, workspace):
        calls.append(target.target_id)
        return dict(status='inconclusive', failure_category=None, latency_ms=1,
                    stages=[dict(check='invoke_model', status='not_tested')], remediation_hint='Verify permissions independently.')
    for _ in range(3):
        response = gateway.foundry.diagnose(tenant, 'azure', 'review', probe)
        assert response['inference_invoked'] is False
    with pytest.raises(AIError) as throttled:
        gateway.foundry.diagnose(tenant, 'azure', 'review', probe)
    assert throttled.value.status == 429 and len(calls) == 3
    assert len(gateway.foundry.diagnostics(TID)) == 3
    assert gateway.foundry.diagnostics(str(uuid4())) == []


def test_monthly_budget_reservation_is_atomic_and_releases_only_metered_usage(evidence):
    _, store, scan = evidence
    ledger = InferenceLedger(store)
    invoked, release = Event(), Event()
    def blocking():
        invoked.set()
        assert release.wait(10)
        return result()
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(ledger.run, TID, str(uuid4()), 'a'*64, 10, blocking,
            metadata=metadata(scan), monthly_token_limit=1000, token_reservation=600)
        assert invoked.wait(5)
        try:
            with pytest.raises(AIError, match='monthly token budget'):
                ledger.run(TID, str(uuid4()), 'b'*64, 10, lambda: pytest.fail('Quota rejected before invoke'),
                    metadata=metadata(scan), monthly_token_limit=1000, token_reservation=600)
        finally:
            release.set()
        first.result()
    assert ledger.window_summary(TID)['monthly_tokens_used_or_reserved'] == 120
    ledger.run(TID, str(uuid4()), 'c'*64, 10, result, metadata=metadata(scan), monthly_token_limit=1000, token_reservation=600)
    assert ledger.window_summary(TID)['monthly_tokens_used_or_reserved'] == 240


def test_unmetered_and_uncertain_attempts_keep_their_token_reservation(evidence):
    _, store, scan = evidence
    ledger = InferenceLedger(store)
    ledger.run(TID, str(uuid4()), 'a'*64, 10, lambda: {'usage': {}}, metadata=metadata(scan),
               monthly_token_limit=1000, token_reservation=600)
    with pytest.raises(AIError, match='monthly token budget'):
        ledger.run(TID, str(uuid4()), 'b'*64, 10, result, metadata=metadata(scan), monthly_token_limit=1000, token_reservation=600)
    assert ledger.window_summary(TID)['monthly_tokens_used_or_reserved'] == 600


def test_unmetered_legacy_outcome_blocks_new_hard_capped_inference(evidence):
    _, store, scan = evidence
    ledger = InferenceLedger(store)
    ledger.run(TID, str(uuid4()), 'a'*64, 10, lambda: {'usage': {}}, metadata=metadata(scan))
    with pytest.raises(AIError, match='Unmetered historical'):
        ledger.run(TID, str(uuid4()), 'b'*64, 10, result, metadata=metadata(scan), monthly_token_limit=10000, token_reservation=600)


def test_idempotent_completed_result_does_not_consume_new_token_budget(evidence):
    _, store, scan = evidence
    ledger = InferenceLedger(store)
    key = str(uuid4())
    first = ledger.run(TID, key, 'a'*64, 10, result, metadata=metadata(scan), monthly_token_limit=1000, token_reservation=600)
    cached = ledger.run(TID, key, 'a'*64, 10, lambda: pytest.fail('Cached result must not invoke'),
        metadata=metadata(scan), monthly_token_limit=1, token_reservation=600)
    assert cached['cached'] and first['assessment_id'] == cached['assessment_id']
    assert ledger.window_summary(TID)['attempts_last_30d'] == 1
