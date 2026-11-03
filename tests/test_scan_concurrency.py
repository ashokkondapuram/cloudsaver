"""Distributed workspace scan lease visibility."""
import os
from uuid import uuid4

import pytest

from app.scan_concurrency import distributed_scan_lease_held


def test_distributed_scan_lease_held_false_when_lock_disabled(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', raising=False)
    assert distributed_scan_lease_held(str(uuid4())) is False


def test_distributed_scan_lease_held_reflects_redis_key(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', 'true')
    tenant = str(uuid4())
    held = False

    class FakeLease:
        def __init__(self, *_args, **_kwargs):
            pass

        def held(self, tid):
            assert tid == tenant
            return held

        def close(self):
            return None

    monkeypatch.setattr('workers.tasks.RedisLease', FakeLease)
    assert distributed_scan_lease_held(tenant) is False
    held = True
    assert distributed_scan_lease_held(tenant) is True


@pytest.mark.parametrize('env', ['true', 'TRUE'])
def test_distributed_scan_lock_enabled_case_insensitive(monkeypatch, env):
    from app.scan_concurrency import distributed_scan_lock_enabled
    monkeypatch.setenv('CLOUDSAVER_DISTRIBUTED_SCAN_LOCK', env)
    assert distributed_scan_lock_enabled() is True
