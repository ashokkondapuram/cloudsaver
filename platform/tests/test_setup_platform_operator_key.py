import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path


def load_setup(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'scripts' / 'setup_platform.py'
    target = tmp_path / 'scripts' / 'setup_platform.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    spec = importlib.util.spec_from_file_location('setup_platform_test', target)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.path = tmp_path / '.env'
    module.operator_key_path = tmp_path / 'operator-access.key'
    module.root = tmp_path
    monkeypatch.chdir(tmp_path)
    return module


def test_create_writes_operator_key_file(tmp_path, monkeypatch):
    mod = load_setup(tmp_path, monkeypatch)
    mod.create()
    key = mod.read_operator_access_key()
    assert key and len(key) >= 32
    env = mod.parse(mod.path)
    assert env['PLATFORM_OPERATOR_KEY_SHA256'] == hashlib.sha256(key.encode()).hexdigest()
    assert mod.operator_key_path.stat().st_mode & 0o777 == 0o600
    assert mod.path.stat().st_mode & 0o777 == 0o600
