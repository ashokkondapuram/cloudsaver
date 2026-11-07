"""Restricted workspace keys must not reveal foreign provider or scope rows."""
from types import SimpleNamespace

import pytest

from app.provider_access import ScopedStore, access


@pytest.mark.parametrize('method', ['findings_for_resource_key', 'findings_for_resource'])
def test_targeted_finding_reads_enforce_provider_and_subscription(method):
    allowed = dict(cloud_provider='azure', subscription_id='allowed', resource_id='/allowed')
    foreign = [dict(allowed, subscription_id='other'), dict(allowed, cloud_provider='aws')]
    inner = SimpleNamespace(**{method: lambda *args: [allowed, *foreign]})
    token = access.set((frozenset({'azure'}), False, {'azure': frozenset({'allowed'})}))
    try:
        args = ('tenant', 'scan', 'key') if method.endswith('_key') else ('tenant', 'scan', 'azure', '/allowed')
        assert getattr(ScopedStore(inner), method)(*args) == [allowed]
    finally:
        access.reset(token)


@pytest.mark.parametrize('observation', [
    dict(cloud_provider='aws', resource_id='foreign'),
    dict(cloud_provider='azure', subscription_id='other', resource_id='foreign'),
])
def test_foreign_resource_bundle_is_non_enumerating(observation):
    inner = SimpleNamespace(scan_resource_bundle=lambda *args: dict(observation=observation, findings=[]))
    token = access.set((frozenset({'azure'}), False, {'azure': frozenset({'allowed'})}))
    try:
        assert ScopedStore(inner).scan_resource_bundle('tenant', 'scan', 'azure', 'foreign') is None
    finally:
        access.reset(token)
