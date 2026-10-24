import copy
import json
from pathlib import Path

import pytest

from identity.ai_policy import DEFAULT_POLICY
from identity.domain import IdentityError, StaleVersion
from test_identity import build, OPERATOR


def test_operator_policy_defaults_to_no_inference_and_updates_are_versioned_and_audited():
    service = build()
    row = service.get_ai_policy()
    assert row['policy']['enabled'] is False
    assert row['policy'] == json.loads((Path(__file__).resolve().parents[1] / 'contracts/fixtures/ai-policy-v2.json').read_text())['policy']
    assert all(not items for items in row['policy']['allowed_models'].values())
    policy = copy.deepcopy(row['policy'])
    policy['allowed_regions']['azure'] = ['eastus']
    changed = service.update_ai_policy({'version': row['version'], 'policy': policy}, OPERATOR)
    assert changed['version'] == row['version'] + 1
    assert service.store.state['events'][-1]['action'] == 'ai_policy_updated'
    with pytest.raises(StaleVersion):
        service.update_ai_policy({'version': row['version'], 'policy': policy}, OPERATOR)


@pytest.mark.parametrize('field,value', [('enabled', 1), ('max_input_tokens_per_request', True),
    ('hourly_attempt_ceiling', 101), ('monthly_token_ceiling', -1), ('disabled_providers', ['azure','azure']),
    ('allowed_models', {'azure': ['unbounded']})])
def test_policy_rejects_ambiguous_or_unbounded_controls(field, value):
    service = build()
    policy = copy.deepcopy(DEFAULT_POLICY)
    policy[field] = value
    with pytest.raises(IdentityError):
        service.update_ai_policy({'version': 1, 'policy': policy}, OPERATOR)
