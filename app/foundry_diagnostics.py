"""Identity and metadata probes. No model invocation, prompt, or client resource data."""
import re
import time

import httpx

from app.ai_advisory import AIError


def is_bedrock_profile(model):
    return model.startswith(('arn:aws:bedrock:', 'us.', 'eu.', 'apac.', 'global.'))


def verify_bedrock_profile(session, target):
    if not is_bedrock_profile(target.model):
        return
    from botocore.config import Config
    with session.client('bedrock', region_name=target.region,
            config=Config(connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 1})) as client:
        profile = client.get_inference_profile(inferenceProfileIdentifier=target.model)
    models = profile.get('models')
    regions = set()
    if not isinstance(models, list) or not models or len(models) > 50 or profile.get('status') != 'ACTIVE':
        raise AIError('Bedrock inference profile metadata is unavailable or inactive.', 403)
    for item in models:
        arn = item.get('modelArn') if isinstance(item, dict) else None
        match = re.fullmatch(r'arn:aws:bedrock:([a-z0-9-]+):[0-9]*:foundation-model/[A-Za-z0-9._:-]+', arn or '')
        if not match:
            raise AIError('Bedrock profile contains an unverified destination.', 403)
        regions.add(match[1])
    if not regions <= set(target.approved_regions):
        raise AIError('Bedrock profile routes outside the approved destination regions.', 403)


def metadata_probe(target, tenant):
    started = time.monotonic()
    stages = []
    category = None
    status = 'inconclusive'
    hint = 'Metadata reads do not prove model invocation RBAC, quota, retention controls or private-network readiness.'
    try:
        if target.provider == 'azure':
            from app.cloud_identity import azure_credential, platform_credential
            with (platform_credential() if target.auth == 'managed_identity' else azure_credential(tenant)) as credential:
                credential.get_token('https://cognitiveservices.azure.com/.default')
                stages.append(dict(check='federated_identity', status='verified'))
                if target.azure_resource_id:
                    token = credential.get_token('https://management.azure.com/.default').token
                    with httpx.Client(timeout=5, follow_redirects=False) as client:
                        response = client.get('https://management.azure.com' + target.azure_resource_id + '/deployments/' + target.model,
                            params={'api-version': '2024-10-01'}, headers={'Authorization': 'Bearer ' + token})
                    response.raise_for_status()
                    if response.json().get('properties', {}).get('provisioningState') != 'Succeeded':
                        raise AIError('Deployment metadata does not indicate readiness.', 403)
                    stages.append(dict(check='deployment_metadata', status='verified'))
                else:
                    stages.append(dict(check='deployment_metadata', status='not_verified', reason='Operator ARM resource binding is not configured.'))
        elif target.provider == 'aws':
            from app.cloud_identity import aws_session
            from botocore.config import Config
            session = aws_session({'region': target.region, 'role_arn': target.role_arn, 'external_id': tenant['tenant_id']})
            with session.client('sts', region_name=target.region,
                    config=Config(connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 1})) as client:
                caller = client.get_caller_identity()
                if caller.get('Account') != target.role_arn.split(':')[4]:
                    raise AIError('Federated caller account does not match the approved role.', 403)
            stages.append(dict(check='federated_identity', status='verified'))
            verify_bedrock_profile(session, target)
            with session.client('bedrock', region_name=target.region,
                    config=Config(connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 1})) as client:
                if not is_bedrock_profile(target.model):
                    client.get_foundation_model(modelIdentifier=target.model)
                stages.append(dict(check='model_metadata', status='verified'))
                if target.guardrail_id:
                    client.get_guardrail(guardrailIdentifier=target.guardrail_id, guardrailVersion=target.guardrail_version)
                    stages.append(dict(check='guardrail_metadata', status='verified'))
        else:
            from app.cloud_identity import gcp_credentials
            from google.auth.transport.requests import Request
            import requests
            credential = gcp_credentials({'service_account': target.service_account}, tenant=tenant,
                                         scopes=['https://www.googleapis.com/auth/cloud-platform'])
            with requests.Session() as session:
                request = Request(session)
                credential.refresh(lambda *args, **kwargs: request(*args, **dict(kwargs, timeout=5)))
            stages.append(dict(check='federated_identity', status='verified'))
            with httpx.Client(timeout=5, follow_redirects=False) as client:
                response = client.get('https://' + target.region + '-aiplatform.googleapis.com/v1/publishers/google/models/' + target.model,
                    headers={'Authorization': 'Bearer ' + credential.token})
            response.raise_for_status()
            stages.append(dict(check='model_metadata', status='verified'))
    except Exception as error:
        from botocore.exceptions import EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError
        from azure.core.exceptions import ServiceRequestError, ServiceResponseError
        from google.auth.exceptions import TransportError
        status = 'failed'
        category = 'identity_federation_failed' if not stages else 'deployment_or_model_not_found'
        if isinstance(error, (httpx.ConnectError, httpx.TimeoutException, EndpointConnectionError,
                              ConnectTimeoutError, ReadTimeoutError, ServiceRequestError, ServiceResponseError, TransportError)):
            category = 'network_or_privatelink_blocked'
        if isinstance(error, httpx.HTTPStatusError):
            code = error.response.status_code
            category = 'missing_model_rbac' if code in (401,403) else 'quota_or_ptu_exhausted' if code == 429 else category
        details = getattr(error, 'response', {})
        if isinstance(details, dict):
            code = (details.get('Error') or {}).get('Code')
            if code in ('AccessDeniedException', 'UnauthorizedOperation'):
                category = 'missing_model_rbac'
            elif code in ('ThrottlingException', 'ServiceQuotaExceededException'):
                category = 'quota_or_ptu_exhausted'
            elif code == 'ResourceNotFoundException' and target.guardrail_id:
                category = 'guardrail_not_found'
        if isinstance(error, AIError) and 'approved destination' in str(error):
            category = 'destination_region_not_approved'
        hint = {'azure': 'Verify the approved deployment and federated identity; grant the required Azure AI data-plane role independently.',
                'aws': 'Verify role federation, approved Bedrock model/regions and GetModel/GetGuardrail permissions; verify InvokeModel separately.',
                'gcp': 'Verify workload federation, regional Gemini availability and Vertex AI permissions in the approved project.'}[target.provider]
    stages.append(dict(check='model_invocation_permissions_and_quota', status='not_tested'))
    return dict(status=status, failure_category=category, remediation_hint=hint, stages=stages,
                latency_ms=round((time.monotonic()-started)*1000), diagnostic_scope='identity_and_metadata_only',
                inference_invoked=False, retention_controls_verified=False)
