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


@pytest.fixture
def provider_protocol_only(monkeypatch):
    """Isolate mocked wire protocols; test_data_governance covers the mandatory public entry gate."""
    monkeypatch.setattr('app.data_governance.require_processing_grant',lambda *_:None)


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
    assert len(public['targets']) == 1 and set(public['targets'][0]) == {'target_id', 'provider', 'model', 'max_output_tokens', 'max_context_bytes', 'allowed_source_providers', 'destination_region', 'max_input_tokens'}
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


@pytest.mark.parametrize('claim', ['Save $120 per month.', 'Savings are USD 100.', 'You save 250 dollars.', 'Run https://invalid.example for approval.'])
def test_unknown_cost_cannot_be_replaced_with_a_model_currency_claim(claim):
    ctx, _ = context()
    with pytest.raises(AIError, match='validation'):
        parse_advice(json.dumps(dict(advice(), summary=claim)), ctx)


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


def test_azure_adapter_uses_tenant_keyless_identity_and_fixed_no_tools_request(monkeypatch, provider_protocol_only):
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
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(advice())}}], 'usage': {'prompt_tokens': 300, 'completion_tokens': 180}}
    monkeypatch.setattr('app.cloud_identity.azure_credential', credential)
    monkeypatch.setattr('app.ai_advisory.post_json', post)
    ctx, _ = context()
    assert CloudAdapter()(Target.model_validate(target()), {'tenant_id': TID}, ctx).advice == advice()
    assert len(calls) == 1


def test_bedrock_adapter_has_no_inference_retries_and_uses_tenant_external_id(monkeypatch, provider_protocol_only):
    from types import SimpleNamespace
    calls = []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def converse(self, **kwargs):
            calls.append(kwargs)
            assert 'toolConfig' not in kwargs and kwargs['modelId'] == 'operator-model'
            return {'stopReason': 'end_turn', 'output': {'message': {'content': [{'text': json.dumps(advice())}]}}, 'usage': {'inputTokens': 300, 'outputTokens': 180}}
    def session(source):
        assert source['external_id'] == TID and source['role_arn'].endswith('/AIReviewer')
        def client(service, **kwargs):
            assert service == 'bedrock-runtime'
            assert kwargs['config'].retries['total_max_attempts'] == 1
            return Client()
        return SimpleNamespace(client=client)
    monkeypatch.setattr('app.cloud_identity.aws_session', session)
    ctx, _ = context()
    assert CloudAdapter()(Target.model_validate(target('aws')), {'tenant_id': TID}, ctx).advice == advice()
    assert len(calls) == 1


def test_vertex_adapter_uses_bound_impersonation_and_cloud_platform_scope(monkeypatch, provider_protocol_only):
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
        return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(advice())}]}}], 'usageMetadata': {'promptTokenCount': 300, 'candidatesTokenCount': 180}}
    monkeypatch.setattr('app.cloud_identity.gcp_credentials', credential)
    monkeypatch.setattr('app.ai_advisory.post_json', post)
    ctx, _ = context()
    assert CloudAdapter()(Target.model_validate(target('gcp')), {'tenant_id': TID}, ctx).advice == advice()
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


def test_pillar_specific_citations_risk_floor_and_missing_risk_references():
    item = dict(azure_disk_finding(SUB),evidence={'encrypted':False,'multi_az':False})
    result = assess(item); ctx = ai_context(item,result)
    valid = advice(); valid['risk_level']='high'
    valid['pillars'][3]['evidence_codes']=['ENCRYPTION_AT_REST']
    assert parse_advice(json.dumps(valid),ctx)['risk_level']=='high'
    invalid = json.loads(json.dumps(valid)); invalid['risk_level']='unknown'
    with pytest.raises(AIError): parse_advice(json.dumps(invalid),ctx)
    invalid = json.loads(json.dumps(valid)); invalid['pillars'][3]['evidence_codes']=[]
    with pytest.raises(AIError): parse_advice(json.dumps(invalid),ctx)
    invalid = json.loads(json.dumps(valid)); invalid['pillars'][0]['evidence_codes']=['ENCRYPTION_AT_REST']
    with pytest.raises(AIError): parse_advice(json.dumps(invalid),ctx)
    invalid = json.loads(json.dumps(valid)); invalid['pillars'][3]['evidence_codes']*=2
    with pytest.raises(AIError): parse_advice(json.dumps(invalid),ctx)


@pytest.mark.parametrize('changes', [dict(max_output_tokens=5000),dict(max_output_tokens=True),
    dict(max_context_bytes=1000),dict(allowed_source_providers=['untrusted'])])
def test_operator_inference_limits_are_strict(changes):
    with pytest.raises(ValidationError): Target.model_validate(dict(target(),**changes))


def test_target_source_and_context_limits_reject_before_attempt_or_inference():
    class Budget:
        def run(self,*args): raise AssertionError('Must reject before reserving a paid attempt')
    ctx,result=context()
    for binding,context_input,status in [
        (dict(target(),allowed_source_providers=['aws']),ctx,403),
        (dict(target(),max_context_bytes=2048),dict(ctx,checks=ctx['checks']*20),422),
    ]:
        gateway=AIGateway(enabled=True,targets=[binding],budget=Budget())
        with pytest.raises(AIError) as error: gateway.evaluate({'tenant_id':TID},'review',uuid4(),'scan',context_input,result)
        assert error.value.status==status


@pytest.mark.parametrize('finish,tools', [('length',None),('content_filter',None),(None,None),('stop',[{'type':'function'}])])
def test_incomplete_filtered_or_tool_provider_response_is_rejected(monkeypatch,finish,tools, provider_protocol_only):
    from types import SimpleNamespace
    class Credential:
        def get_token(self,scope): return SimpleNamespace(token='test-only')
        def __enter__(self): return self
        def __exit__(self,*args): pass
    monkeypatch.setattr('app.cloud_identity.azure_credential',lambda tenant:Credential())
    monkeypatch.setattr('app.ai_advisory.post_json',lambda *args,**kwargs:{'choices':[{'finish_reason':finish,
        'message':{'content':json.dumps(advice()),'tool_calls':tools}}]})
    ctx,_=context()
    with pytest.raises(AIError) as error: CloudAdapter()(Target.model_validate(target()),{'tenant_id':TID},ctx)
    assert error.value.status==502


def test_usage_is_provider_metadata_and_missing_values_remain_unknown():
    from app.ai_advisory import InferenceResult, token_usage
    assert token_usage({'in':True,'out':-2},'in','out')['input_tokens'] is None
    assert token_usage({'in':0,'out':0},'in','out')['output_tokens']==0
    class Budget:
        def run(self,tid,key,fingerprint,limit,invoke): return dict(invoke(),cached=False)
    ctx,result=context()
    gateway=AIGateway(enabled=True,targets=[target()],budget=Budget(),adapter=lambda *args:InferenceResult(advice(),token_usage({'in':300,'out':180},'in','out')))
    response=gateway.evaluate({'tenant_id':TID},'review',uuid4(),'scan',ctx,result)
    assert response['usage']==dict(input_tokens=300,output_tokens=180,source='provider_reported',billed_cost_usd=None)
    assert response['validation']['semantic_claims_verified'] is False
    assert response['evidence_digest']==result['evidence_digest']
    assert response['assessment_policy_version']==result['policy_version']


def test_ambiguous_duplicate_json_properties_are_rejected():
    ctx,_=context()
    raw=json.dumps(advice()).replace('{','{"summary":"conflicting value",',1)
    with pytest.raises(AIError,match='validation'): parse_advice(raw,ctx)


@pytest.mark.parametrize('provider,finish', [('aws','max_tokens'),('aws','tool_use'),('aws',None),
                                          ('gcp','MAX_TOKENS'),('gcp','SAFETY'),('gcp',None)])
def test_other_providers_reject_nonterminal_or_filtered_results(monkeypatch,provider,finish, provider_protocol_only):
    from types import SimpleNamespace
    if provider=='aws':
        class Client:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def converse(self,**kwargs):
                return {'stopReason':finish,'output':{'message':{'content':[{'text':json.dumps(advice())}]}}}
        monkeypatch.setattr('app.cloud_identity.aws_session',lambda source:SimpleNamespace(client=lambda *args,**kwargs:Client()))
    else:
        class Credential:
            token='test-only'
            def refresh(self,request): pass
        monkeypatch.setattr('app.cloud_identity.gcp_credentials',lambda *args,**kwargs:Credential())
        monkeypatch.setattr('app.ai_advisory.post_json',lambda *args,**kwargs:{'candidates':[{'finishReason':finish,'content':{'parts':[{'text':json.dumps(advice())}]}}]})
    ctx,_=context()
    with pytest.raises(AIError) as error: CloudAdapter()(Target.model_validate(target(provider)),{'tenant_id':TID},ctx)
    assert error.value.status==502
