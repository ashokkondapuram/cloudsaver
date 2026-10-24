"""Operator-owned AI guardrails. No customer endpoints, credentials or payloads belong here."""
import copy
import re

from identity.domain import IdentityError, StaleVersion, iso
from identity.data_policy import DEFAULT_DATA_GOVERNANCE,validate_data_governance

DEFAULT_POLICY = dict(enabled=False, allowed_providers=['azure', 'aws', 'gcp'],
    disabled_providers=[], allowed_models={'azure': [], 'aws': [], 'gcp': []},
    allowed_regions={'azure': [], 'aws': [], 'gcp': []}, allow_cross_provider=False,
    max_input_tokens_per_request=4000, max_output_tokens_per_request=1200,
    hourly_attempt_ceiling=10, monthly_token_ceiling=1000000, allow_knowledge_candidates=False,
    data_governance=copy.deepcopy(DEFAULT_DATA_GOVERNANCE))


def validate_policy(value):
    if not isinstance(value, dict) or set(value)-{'data_governance'} != set(DEFAULT_POLICY)-{'data_governance'}:
        raise IdentityError('Provide the complete supported AI policy.')
    for field in ('enabled', 'allow_cross_provider', 'allow_knowledge_candidates'):
        if type(value[field]) is not bool:
            raise IdentityError('AI policy switches must be booleans.')
    providers = {'azure', 'aws', 'gcp'}
    for field in ('allowed_providers', 'disabled_providers'):
        items = value[field]
        if not isinstance(items, list) or any(not isinstance(item, str) or item not in providers for item in items) or len(items) != len(set(items)):
            raise IdentityError('Choose unique supported AI providers.')
    for field in ('allowed_models', 'allowed_regions'):
        mapping = value[field]
        if not isinstance(mapping, dict) or set(mapping) != providers:
            raise IdentityError('Provide explicit model and region allowlists for every provider.')
        for items in mapping.values():
            if (not isinstance(items, list) or len(items) > 100 or any(not isinstance(item, str) or
                    not re.fullmatch(r'[A-Za-z0-9._:/-]{1,512}', item) for item in items)):
                raise IdentityError('Invalid AI model or region allowlist.')
    for field, low, high in (('max_input_tokens_per_request', 256, 16000),
        ('max_output_tokens_per_request', 256, 4096), ('hourly_attempt_ceiling', 1, 100),
        ('monthly_token_ceiling', 512, 1000000000)):
        if type(value[field]) is not int or not low <= value[field] <= high:
            raise IdentityError('AI policy budget is outside supported bounds.')
    try:
        governance=validate_data_governance(value.get('data_governance',DEFAULT_DATA_GOVERNANCE))
    except (ValueError,TypeError,KeyError):
        raise IdentityError('AI data policy is invalid. Register explicit, reviewed processors and prohibited reuse controls.') from None
    return dict(copy.deepcopy(value),data_governance=governance)


class AIPolicyOps:
    def get_ai_policy(self):
        with self.store.transaction() as tx:
            row = tx.get_ai_policy()
        return dict(policy=validate_policy(row['policy']), version=row['version'], updated_at=iso(row['updated_at']), updated_by=row['updated_by'])

    def update_ai_policy(self, payload, actor, request_id=None):
        version = self._version(payload)
        policy = validate_policy(payload.get('policy'))
        with self.store.transaction() as tx:
            row = tx.update_ai_policy(version, dict(policy=policy, updated_at=self.now(), updated_by=actor['actor'][:120]))
            if not row:
                raise StaleVersion()
            self._event(tx, actor, 'ai_policy_updated', details={'version': row['version']}, request_id=request_id)
            self._publish([{'event': 'ai_policy_changed'}], tx)
        return self.get_ai_policy()
