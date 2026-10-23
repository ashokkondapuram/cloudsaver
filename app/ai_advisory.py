"""Opt-in, tenant-bound cloud inference. The model has no tools or execution authority."""
import hashlib
import json
import os
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIError(RuntimeError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    target_id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    tenant_id: UUID
    provider: Literal['azure', 'aws', 'gcp']
    model: str = Field(pattern=r'^[A-Za-z0-9._:-]{1,160}$')
    endpoint: str | None = None
    region: str | None = None
    role_arn: str | None = None
    project: str | None = None
    service_account: str | None = None

    @model_validator(mode='after')
    def binding(self):
        if self.provider == 'azure':
            parsed = urlsplit(self.endpoint or '')
            if (parsed.scheme != 'https' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,62}\.openai\.azure\.com', parsed.hostname or '')
                    or parsed.port not in (None, 443) or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                    or parsed.username or parsed.password or any((self.region, self.role_arn, self.project, self.service_account))):
                raise ValueError('Azure requires an approved HTTPS Azure OpenAI root endpoint only')
        elif self.provider == 'aws':
            if (not re.fullmatch(r'[a-z]{2}-[a-z0-9-]{2,24}-[0-9]', self.region or '')
                    or not re.fullmatch(r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}', self.role_arn or '')
                    or any((self.endpoint, self.project, self.service_account))):
                raise ValueError('Bedrock requires an operator-bound region and role ARN')
        else:
            if (not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', self.project or '')
                    or not re.fullmatch(r'[a-z]+-[a-z]+[0-9]', self.region or '')
                    or not re.fullmatch(r'[a-z0-9-]{6,30}@' + re.escape(self.project or '') + r'\.iam\.gserviceaccount\.com', self.service_account or '')
                    or any((self.endpoint, self.role_arn))):
                raise ValueError('Vertex requires an operator-bound regional project and service account')
        return self


class PillarAdvice(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    pillar: Literal['cost', 'reliability', 'performance', 'security', 'operations']
    observation: str = Field(min_length=1, max_length=700)
    evidence_codes: list[str] = Field(max_length=12)


class Advice(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    summary: str = Field(min_length=1, max_length=1000)
    risk_level: Literal['high', 'unknown']
    pillars: list[PillarAdvice] = Field(min_length=5, max_length=5)
    review_questions: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode='after')
    def complete(self):
        if {p.pillar for p in self.pillars} != {'cost', 'reliability', 'performance', 'security', 'operations'}:
            raise ValueError('Exactly one response per pillar is required')
        if any(not 1 <= len(q) <= 400 for q in self.review_questions):
            raise ValueError('Review question length is invalid')
        return self


SYSTEM = '''You are an advisory FinOps reviewer. Input contains allowlisted saved facts, not a live dependency graph.
Missing evidence means unknown. A stopped or orphaned signal does not establish idle duration, savings or deletability.
Never claim an action is approved or safe. Do not generate code, commands, IaC, URLs, tools, or execution instructions.
Protected recovery/witness/retention resources must remain protected. No savings or dependency claims beyond supplied facts.
Return only a JSON object: summary (string), risk_level (high or unknown), pillars (exactly five objects with pillar
cost/reliability/performance/security/operations, observation string, evidence_codes list drawn ONLY from observed_check_codes),
review_questions (1-6 strings). State evidence gaps and independent verification questions. No additional properties.'''


def parse_advice(raw, context):
    if not isinstance(raw, str) or len(raw.encode()) > 16000:
        raise AIError('AI response exceeded the allowed schema', 502)
    try:
        result = Advice.model_validate_json(raw)
        allowed = set(context['observed_check_codes'])
        if any(not set(p.evidence_codes) <= allowed for p in result.pillars):
            raise ValueError('Unsupported evidence citation')
    except (ValueError, TypeError):
        raise AIError('AI response failed validation; no approval or artifact was produced', 502) from None
    return result.model_dump()


def post_json(url, token, payload, *, transport=None):
    # No redirects, implicit retries, raw errors, or unbounded response bodies.
    with httpx.Client(timeout=httpx.Timeout(35, connect=5), follow_redirects=False, transport=transport) as client:
        with client.stream('POST', url, headers={'Authorization': 'Bearer ' + token}, json=payload) as response:
            if response.status_code != 200:
                raise AIError('AI provider did not complete the request', 502)
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise AIError('AI provider response exceeded the size limit', 502)
            return json.loads(body)


class CloudAdapter:
    def __call__(self, target, tenant, context):
        payload = json.dumps(context, sort_keys=True, separators=(',', ':'))
        try:
            if target.provider == 'azure':
                from app.cloud_identity import azure_credential
                with azure_credential(tenant) as credential:
                    token = credential.get_token('https://cognitiveservices.azure.com/.default').token
                    result = post_json(target.endpoint.rstrip('/') + '/openai/deployments/' + target.model + '/chat/completions?api-version=2024-10-21', token,
                        {'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': payload}],
                         'max_tokens': 1800, 'temperature': 0, 'response_format': {'type': 'json_object'}})
                raw = result['choices'][0]['message']['content']
            elif target.provider == 'aws':
                from app.cloud_identity import aws_session
                from botocore.config import Config
                session = aws_session({'region': target.region, 'role_arn': target.role_arn, 'external_id': tenant['tenant_id']})
                with session.client('bedrock-runtime', region_name=target.region,
                        config=Config(connect_timeout=5, read_timeout=35, retries={'total_max_attempts': 1})) as client:
                    result = client.converse(modelId=target.model, system=[{'text': SYSTEM}],
                        messages=[{'role': 'user', 'content': [{'text': payload}]}],
                        inferenceConfig={'maxTokens': 1800, 'temperature': 0})
                raw = ''.join(part['text'] for part in result['output']['message']['content'] if 'text' in part)
            else:
                from app.cloud_identity import gcp_credentials
                from google.auth.transport.requests import Request
                import requests
                credential = gcp_credentials({'service_account': target.service_account}, scopes=['https://www.googleapis.com/auth/cloud-platform'])
                with requests.Session() as session:
                    # Google auth may make multiple federation requests; bound each one.
                    request = Request(session=session)
                    credential.refresh(lambda *args, **kwargs: request(*args, **dict(kwargs, timeout=10)))
                url = f'https://{target.region}-aiplatform.googleapis.com/v1/projects/{target.project}/locations/{target.region}/publishers/google/models/{target.model}:generateContent'
                result = post_json(url, credential.token, {'systemInstruction': {'parts': [{'text': SYSTEM}]},
                    'contents': [{'role': 'user', 'parts': [{'text': payload}]}],
                    'generationConfig': {'maxOutputTokens': 1800, 'temperature': 0, 'responseMimeType': 'application/json'}})
                raw = ''.join(part['text'] for part in result['candidates'][0]['content']['parts'] if 'text' in part)
            return parse_advice(raw, context)
        except AIError:
            raise
        except Exception:
            raise AIError('AI provider unavailable or response invalid; the outcome is uncertain', 502) from None


class RedisBudget:
    """An atomic attempt budget and idempotency fence, shared across API replicas.

    A pending/uncertain attempt is never automatically repeated. Redis retention is
    24 hours, not a permanent audit or exactly-once inference guarantee.
    """
    CLAIM = '''
      local prior=redis.call('GET',KEYS[1])
      if prior then return prior end
      local t=redis.call('TIME'); local bucket=math.floor(tonumber(t[1])/3600)
      local budget=KEYS[2]..':'..bucket
      if tonumber(redis.call('GET',budget) or '0')>=tonumber(ARGV[2]) then return 'limit' end
      redis.call('INCR',budget); redis.call('EXPIRE',budget,3900)
      redis.call('SET',KEYS[1],ARGV[1],'EX',86400)
      return 'claimed'
    '''

    FINISH = '''
      if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end
      redis.call('SET',KEYS[1],ARGV[2],'EX',86400)
      return 1
    '''

    def __init__(self, url=None):
        self.url = url or os.getenv('REDIS_URL', 'redis://redis:6379/1')

    def run(self, tenant_id, key, fingerprint, limit, invoke):
        import redis
        record_key = 'cloudsaver:ai:v1:' + tenant_id + ':' + key
        pending = json.dumps({'fingerprint': fingerprint, 'status': 'uncertain', 'owner': str(uuid4())})
        try:
            client = redis.from_url(self.url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
            with client:
                prior = client.eval(self.CLAIM, 2, record_key, 'cloudsaver:ai:budget:' + tenant_id, pending, limit)
                if prior == 'limit':
                    raise AIError('Workspace AI hourly attempt budget reached', 429)
                if prior != 'claimed':
                    record = json.loads(prior)
                    if record['fingerprint'] != fingerprint:
                        raise AIError('Idempotency key belongs to a different request', 409)
                    if record['status'] != 'completed':
                        raise AIError('This AI attempt is pending or uncertain; it will not be repeated automatically', 409)
                    return dict(record['response'], cached=True)
                # After this point, any failure leaves the fence in place.
                response = invoke()
                completed = json.dumps({'fingerprint': fingerprint, 'status': 'completed', 'response': response})
                if not client.eval(self.FINISH, 1, record_key, pending, completed):
                    raise AIError('AI attempt ownership was lost; its result was not cached', 409)
                return dict(response, cached=False)
        except AIError:
            raise
        except Exception:
            raise AIError('AI coordination unavailable or outcome uncertain; no automatic retry was issued') from None


class AIGateway:
    def __init__(self, *, targets=None, enabled=None, budget=None, adapter=None, limit=None):
        self.enabled = os.getenv('CLOUDSAVER_AI_ENABLED', '').lower() == 'true' if enabled is None else enabled
        raw = json.loads(os.getenv('CLOUDSAVER_AI_TARGETS', '[]')) if targets is None and self.enabled else (targets or [])
        if not isinstance(raw, list) or len(raw) > 1000:
            raise ValueError('AI targets must be a bounded list')
        try:
            self.targets = [Target.model_validate(t) for t in raw]
        except ValueError:
            raise ValueError('Invalid AI target configuration; use documented non-secret tenant bindings') from None
        if len({(t.tenant_id, t.target_id) for t in self.targets}) != len(self.targets):
            raise ValueError('Duplicate tenant AI target')
        self.budget, self.adapter = budget or RedisBudget(), adapter or CloudAdapter()
        self.limit = int(os.getenv('CLOUDSAVER_AI_HOURLY_ATTEMPTS', '10')) if limit is None else limit
        if not 1 <= self.limit <= 100:
            raise ValueError('AI attempt limit must be between 1 and 100')

    def available(self, tenant):
        return {'enabled': self.enabled, 'hourly_attempt_limit': self.limit, 'advisory_only': True,
                'targets': [dict(target_id=t.target_id, provider=t.provider, model=t.model)
                            for t in self.targets if self.enabled and str(t.tenant_id) == tenant['tenant_id']]}

    def evaluate(self, tenant, target_id, key, scan_id, context, assessment):
        target = next((t for t in self.targets if str(t.tenant_id) == tenant['tenant_id'] and t.target_id == target_id), None)
        if not self.enabled or target is None:
            raise AIError('AI target is unavailable for this workspace', 404)
        fingerprint = hashlib.sha256(json.dumps({'target': target.model_dump(mode='json'), 'scan': scan_id,
                                                'context': context, 'schema': 1}, sort_keys=True).encode()).hexdigest()
        def invoke():
            advice = self.adapter(target, tenant, context)
            # Revalidate dependency-injected adapters as well. Citations must reference saved evidence.
            advice = parse_advice(json.dumps(advice), context)
            return dict(advisory_only=True, automatic_execution=False, target_id=target_id, provider=target.provider,
                        model=target.model, scan_id=scan_id, resource_reference=context['resource_reference'],
                        deterministic_disposition=assessment['disposition'], guardrails=assessment['guardrails'],
                        advice=advice, warning='AI text is unverified advice. It does not approve actions or establish a dependency graph, billing savings or live state.')
        return self.budget.run(tenant['tenant_id'], str(key), fingerprint, self.limit, invoke)
