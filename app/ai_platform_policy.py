"""Read current control-plane policy; failure never falls back to permissive cached values."""
import json
import os

from app.ai_advisory import AIError


def validate(value):
    if isinstance(value,dict):value={k:v for k,v in value.items() if k != 'allow_knowledge_candidates'}
    required = {'enabled', 'allowed_providers', 'disabled_providers', 'allowed_models', 'allowed_regions',
        'allow_cross_provider', 'max_input_tokens_per_request', 'max_output_tokens_per_request',
        'hourly_attempt_ceiling', 'monthly_token_ceiling'}
    if not isinstance(value, dict) or set(value)-{'data_governance'} != required:
        raise ValueError('Incomplete policy')
    for key in ('enabled', 'allow_cross_provider'):
        if type(value[key]) is not bool:
            raise ValueError('Invalid switch')
    for key, low, high in (('max_input_tokens_per_request', 256, 16000), ('max_output_tokens_per_request', 256, 4096),
                          ('hourly_attempt_ceiling', 1, 100), ('monthly_token_ceiling', 512, 1000000000)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError('Invalid ceiling')
    for key in ('allowed_providers', 'disabled_providers'):
        if not isinstance(value[key], list) or any(item not in ('azure', 'aws', 'gcp') for item in value[key]):
            raise ValueError('Invalid provider')
    for key in ('allowed_models', 'allowed_regions'):
        if (not isinstance(value[key], dict) or set(value[key]) != {'azure', 'aws', 'gcp'}
                or any(not isinstance(items, list) or len(items) > 100 or any(not isinstance(item, str) for item in items)
                       for items in value[key].values())):
            raise ValueError('Invalid allowlist')
    from app.data_policy import DEFAULT_DATA_GOVERNANCE,validate_data_governance
    return dict(value,data_governance=validate_data_governance(value.get('data_governance',DEFAULT_DATA_GOVERNANCE)))


def current():
    from app.config import key_verifier
    from app.identity_client import shared_client, IdentityUnavailable
    try:
        if key_verifier() in ('identity', 'shadow'):
            response = shared_client().get('/internal/v1/ai-policy', timeout=3)
            if response.status_code != 200:
                raise ValueError('Policy unavailable')
            row = response.json()
        else:
            row = json.loads(os.getenv('CLOUDSAVER_AI_PLATFORM_POLICY', '{}'))
        if type(row.get('version')) is not int or row['version'] < 1:
            raise ValueError('Invalid policy version')
        return dict(version=row['version'], policy=validate(row['policy']))
    except (KeyError, ValueError, TypeError, RuntimeError, IdentityUnavailable):
        raise AIError('Current platform AI policy is unavailable. Inference is blocked.', 503) from None
