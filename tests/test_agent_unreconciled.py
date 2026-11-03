"""Agent task reconciliation flags for paired GitOps programs."""
from app.agent_store import unreconciled


def test_unreconciled_after_succeeded_metadata_write_with_gitops():
    payload = {
        'plan': {'steps': [
            {'operation': 'resource.inspect'},
            {'operation': 'tags.merge'},
            {'operation': 'gitops.terraform.sync'},
        ]},
        'steps': [
            {'state': 'succeeded'},
            {'state': 'succeeded'},
            {'state': 'failed'},
        ],
    }
    assert unreconciled(payload)


def test_unreconciled_after_succeeded_compute_resize_with_gitops():
    payload = {
        'plan': {'steps': [
            {'operation': 'resource.inspect'},
            {'operation': 'compute.resize'},
            {'operation': 'gitops.terraform.sync'},
        ]},
        'steps': [
            {'state': 'succeeded'},
            {'state': 'succeeded'},
            {'state': 'uncertain'},
        ],
    }
    assert unreconciled(payload)
