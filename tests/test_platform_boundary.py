"""CloudSaver talks to the platform only over HTTP (platform/contracts); it never imports platform code."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('app', 'services', 'workers', 'database', 'migrations', 'scripts', 'tests')
PLATFORM_MODULES = ('identity', 'platform.identity', 'platform.portal', 'platform.billing')


def sources():
    for package in PACKAGES:
        yield from sorted((ROOT / package).rglob('*.py'))


def forbidden(module):
    return any(module == name or module.startswith(name + '.') for name in PLATFORM_MODULES)


def test_no_cloudsaver_module_imports_platform_code():
    offenders = []
    for path in sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module] + [f'{node.module}.{alias.name}' for alias in node.names]
            elif isinstance(node, ast.Call) and getattr(node.func, 'attr', getattr(node.func, 'id', '')) in (
                    'import_module', '__import__') and node.args and isinstance(node.args[0], ast.Constant):
                modules = [str(node.args[0].value)]
            else:
                continue
            offenders += [f'{path.relative_to(ROOT)}:{node.lineno} {m}' for m in modules if forbidden(m)]
    assert not offenders, 'CloudSaver must call the platform over HTTP instead:\n' + '\n'.join(offenders)


def test_no_cloudsaver_module_adds_platform_to_the_import_path():
    offenders = []
    for path in sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('insert', 'append')
                    and ast.unparse(node.func.value) == 'sys.path' and 'platform' in ast.unparse(node)):
                offenders.append(f'{path.relative_to(ROOT)}:{node.lineno}')
    assert not offenders, offenders


def test_the_old_identity_package_is_gone_from_the_cloudsaver_tree():
    assert not (ROOT / 'identity').exists() and not (ROOT / 'identity_migrations').exists()
