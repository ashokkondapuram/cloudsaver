import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.ai_advisory import AIError, AIGateway, CloudAdapter, Target, parse_advice, post_json
from app.assessment import PILLARS, assess, ai_context
from tests.support import azure_disk_finding

TID = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'


def target(provider='azure', **kwargs):
    binding = {'azure': {'endpoint': 'https://approved.openai.azure.com'},
               'aws': {'region': 'us-east-1', 'role_arn': 'arn:aws:iam::123456789012:role/AIReviewer'},
               'gcp': {'region': 'us-central1', 'project': 'tenant-project', 'service_account': 'reviewer@tenant-project.iam.gserviceaccount.com'}}[provider]
    return dict(target_id='review', tenant_id=TID, provider=provider, model='operator-model', **dict(binding, **kwargs))


def advice():
    return dict(summary='Saved evidence is incomplete.', risk_level='unknown',
                pillars=[dict(pillar=p, observation='Independent verification is required.', evidence_codes=[]) for p in PILLARS],
                review_questions=['Who owns this resource and its recovery obligations?'])


def context():
    item = azure_disk_finding(SUB)
    result = assess(item)
    return ai_context(item, result), result


@pytest.mark.parametrize('endpoint', ['http://approved.openai.azure.com', 'https://evil.example',
    'https://approved.openai.azure.com.evil.example', 'https://user@approved.openai.azure.com',
    'https://approved.openai.azure.com?secret=x', 'https://approved.openai.azure.com/path', 'https://approved.openai.azure.com:8443'])
def test_target_rejects_unapproved_endpoints(endpoint):
    with pytest.raises(ValidationError):
        Target.model_validate(target(endpoint=endpoint))


@pytest.mark.parametrize('provider', ['azure', 'aws', 'gcp'])
def test_operator_bound_targets_validate_and_never_expose_identity_bindings(provider):
    gateway = AIGateway(targets=[target(provider)], enabled=True)
    public = gateway.available({'tenant_id': TID})
    assert len(public['targets']) == 1 and set(public['targets'][0]) == {'target_id', 'provider', 'model'}
    assert gateway.available({'tenant_id': str(uuid4())})['targets'] == []
    assert not AIGateway(targets=[target(provider)], enabled=False).available({'tenant_id': TID})['targets']


def test_invalid_model_output_approval_code_and_fabricated_citations_are_rejected():
    ctx, _ = context()
    for invalid in [dict(advice(), approval_status='APPROVED'), dict(advice(), terraform='resource {}'),
                    dict(advice(), risk_level='safe'), dict(advice(), pillars=advice()['pillars'][:4])]:
        with pytest.raises(AIError, match='validation'):
            parse_advice(json.dumps(invalid), ctx)
    invalid = advice(); invalid['pillars'][0]['evidence_codes'] = ['INVENTED_LIVE_DEPENDENCY_GRAPH']
    with pytest.raises(AIError):
        parse_advice(json.dumps(invalid), ctx)
    assert parse_advice(json.dumps(advice()), ctx) == advice()


def test_http_adapter_blocks_redirects_oversized_errors_and_raw_messages():
    for response in [httpx.Response(302, headers={'location': 'https://evil.invalid'}),
                     httpx.Response(500, text='private-provider-message'), httpx.Response(200, content=b'x' * 65537)]:
        calls = []
        def handler(request):
            calls.append(request)
            return response
        with pytest.raises(AIError) as error:
            post_json('https://approved.openai.azure.com', 'ephemeral-token', {}, transport=httpx.MockTransport(handler))
        assert len(calls) == 1 and 'private-provider' not in str(error.value)


def test_azure_adapter_uses_tenant_keyless_identity_and_fixed_no_tools_request(monkeypatch):
    from types import SimpleNamespace
    calls = []
    class Credential:
        def get_token(self, scope):
            assert scope == 'https://cognitiveservices.azure.com/.default'
            return SimpleNamespace(token='ephemeral-token')
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def credential(tenant):
        assert tenant['tenant_id'] == TID
        return Credential()
    def post(url, token, body):
        calls.append(body)
        assert url.startswith('https://approved.openai.azure.com/openai/deployments/operator-model/')
        assert token == 'ephemeral-token' and 'tools' not in body and body['max_tokens'] == 1800
        return {'choices': [{'message': {'content': json.dumps(advice())}}]}
    monkeypatch.setattr('app.cloud_identity.azure_credential', credential)
    monkeypatch.setattr('app.ai_advisory.post_json', post)
    ctx, _ = context()
    assert CloudAdapter()(Target.model_validate(target()), {'tenant_id': TID}, ctx) == advice()
    assert len(calls) == 1


def test_bedrock_adapter_has_no_inference_retries_and_uses_tenant_external_id(monkeypatch):
    from types import SimpleNamespace
    calls = []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def converse(self, **kwargs):
            calls.append(kwargs)
            assert 'toolConfig' not in kwargs and kwargs['modelId'] == 'operator-model'
            return {'output': {'message': {'content': [{'text': json.dumps(advice())}]}}}
    def session(source):
        assert source['external_id'] == TID and source['role_arn'].endswith('/AIReviewer')
        def client(service, **kwargs):
            assert service == 'bedrock-runtime'
            assert kwargs['config'].retries['total_max_attempts'] == 1
            return Client()
        return SimpleNamespace(client=client)
    monkeypatch.setattr('app.cloud_identity.aws_session', session)
    ctx, _ = context()
    assert CloudAdapter()(Target.model_validate(target('aws')), {'tenant_id': TID}, ctx) == advice()
    assert len(calls) == 1


def test_vertex_adapter_uses_bound_impersonation_and_cloud_platform_scope(monkeypatch):
    calls = []
    class Credential:
        token = 'ephemeral-token'
        def refresh(self, request): pass
    def credential(source, *, scopes):
        assert source == {'service_account': 'reviewer@tenant-project.iam.gserviceaccount.com'}
        assert scopes == ['https://www.googleapis.com/auth/cloud-platform']
        return Credential()
    def post(url, token, body):
        calls.append(body)
        assert url == 'https://us-central1-aiplatform.googleapis.com/v1/projects/tenant-project/locations/us-central1/publishers/google/models/operator-model:generateContent'
        assert body['generationConfig']['responseMimeType'] == 'application/json' and 'tools' not in body
        return {'candidates': [{'content': {'parts': [{'text': json.dumps(advice())}]}}]}
    monkeypatch.setattr('app.cloud_identity.gcp_credentials', credential)
    monkeypatch.setattr('app.ai_advisory.post_json', post)
    ctx, _ = context()
    assert CloudAdapter()(Target.model_validate(target('gcp')), {'tenant_id': TID}, ctx) == advice()
    assert len(calls) == 1


def test_unconfigured_or_foreign_target_never_invokes_budget_or_provider():
    class Budget:
        def run(self, *args): raise AssertionError('Budget must not be reached')
    gateway = AIGateway(enabled=True, targets=[target()], budget=Budget())
    ctx, result = context()
    with pytest.raises(AIError) as error:
        gateway.evaluate({'tenant_id': str(uuid4())}, 'review', uuid4(), str(uuid4()), ctx, result)
    assert error.value.status == 404


def test_gateway_configuration_errors_do_not_echo_unknown_secret_values():
    with pytest.raises(ValueError) as error:
        AIGateway(enabled=True, targets=[dict(target(), api_key='private-value-must-not-appear')])
    assert 'private-value' not in str(error.value)
