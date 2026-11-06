"""Provider boundaries for analysis rules and evidence checks."""
from __future__ import annotations

_SHARED = ('*',)


def rule_provider(rule_id: str) -> str:
    rid = (rule_id or '').upper()
    if rid.startswith('AZURE_'):
        return 'azure'
    if rid.startswith('AWS_'):
        return 'aws'
    if rid.startswith('GCP_'):
        return 'gcp'
    if rid.startswith('K8S_'):
        return 'kubernetes'
    return 'azure'


def provider_label(provider: str) -> str:
    return {
        'azure': 'Azure',
        'aws': 'AWS',
        'gcp': 'Google Cloud',
        'kubernetes': 'Kubernetes',
        '*': 'Shared',
    }.get(provider, provider)


def group_checks(checks: list[dict], provider: str) -> list[dict]:
    """Split saved checks into shared baseline vs this resource's cloud provider."""
    shared, scoped = [], []
    for row in checks:
        allowed = row.get('providers') or _SHARED
        if '*' in allowed:
            shared.append(row)
        elif provider in allowed:
            scoped.append(row)
    groups = []
    if shared:
        groups.append(dict(scope='shared', provider='*', label='Shared evidence policy', checks=shared))
    if scoped:
        groups.append(
            dict(
                scope='provider',
                provider=provider,
                label=f'{provider_label(provider)} control checks',
                checks=scoped,
            )
        )
    return groups
