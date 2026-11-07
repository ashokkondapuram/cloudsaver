import hashlib
from pathlib import Path

import pytest

from identity.auth import OperatorAuth
from identity import config


def test_operator_key_sha256_from_file(tmp_path, monkeypatch):
    key = 'kubernetes-dev-operator-key'
    path = tmp_path / 'operator-access.key'
    path.write_text(key + '\n')
    monkeypatch.delenv('PLATFORM_OPERATOR_KEY_SHA256', raising=False)
    monkeypatch.delenv('PLATFORM_OPERATOR_ACCESS_KEY', raising=False)
    monkeypatch.setenv('PLATFORM_OPERATOR_ACCESS_KEY_FILE', str(path))
    assert config.operator_key_sha256() == hashlib.sha256(key.encode()).hexdigest()
    auth = OperatorAuth(mode='operator_key', environment='development')
    actor = auth.authenticate(key)
    assert actor['actor_type'] == 'operator'


def test_operator_key_sha256_digest_env_wins(tmp_path, monkeypatch):
    path = tmp_path / 'operator-access.key'
    path.write_text('from-file\n')
    monkeypatch.setenv('PLATFORM_OPERATOR_ACCESS_KEY_FILE', str(path))
    digest = hashlib.sha256(b'from-env').hexdigest()
    monkeypatch.setenv('PLATFORM_OPERATOR_KEY_SHA256', digest)
    assert config.operator_key_sha256() == digest


def test_operator_key_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv('PLATFORM_OPERATOR_ACCESS_KEY_FILE', str(tmp_path / 'missing'))
    monkeypatch.delenv('PLATFORM_OPERATOR_KEY_SHA256', raising=False)
    monkeypatch.delenv('PLATFORM_OPERATOR_ACCESS_KEY', raising=False)
    assert config.operator_key_sha256() == ''
