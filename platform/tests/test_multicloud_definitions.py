"""Platform catalog must not import CloudSaver's app package (identity-migrate image)."""
import subprocess
import sys
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]


def test_definitions_import_isolated_from_app():
    code = (
        'import sys; '
        f"sys.path.insert(0, {repr(str(PLATFORM))}); "
        'from identity.analysis.multicloud import definitions; '
        'assert len(definitions()) >= 36'
    )
    subprocess.run([sys.executable, '-c', code], check=True, env={'PYTHONPATH': str(PLATFORM)})
