"""Package source and a matching SHA-256 manifest, excluding local credentials/data."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path(__file__).resolve().parents[1]
excluded = {'.venv', 'node_modules', '.next', '__pycache__', '.pytest_cache', 'data', 'test-results', 'playwright-report',
            '.git', 'pytest-of-root'}
files = sorted(p for p in root.rglob('*') if p.is_file()
               and not any(part in excluded for part in p.relative_to(root).parts)
               and not (p.name.startswith('.env') and p.name != '.env.example')
               and p.name not in {'RELEASE_MANIFEST.json', 'tsconfig.tsbuildinfo'})
manifest = {'version': '1.0.0', 'files': [
    {'path': p.relative_to(root).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
     'bytes': p.stat().st_size} for p in files]}
manifest_path = root / 'RELEASE_MANIFEST.json'
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
destination = Path(sys.argv[1]) if len(sys.argv) > 1 else root.parent / 'releases' / 'CloudSaver-v1.0.0-integrated.zip'
destination.parent.mkdir(parents=True, exist_ok=True)
with ZipFile(destination, 'w', compression=ZIP_DEFLATED) as archive:
    for path in files + [manifest_path]:
        info = ZipInfo('cloudsaver/' + path.relative_to(root).as_posix())
        info.compress_type = ZIP_DEFLATED
        info.create_system = 3
        mode = 0o755 if path.name == 'init.sh' else 0o644
        info.external_attr = (0o100000 | mode) << 16
        archive.writestr(info, path.read_bytes())
print(f'{destination}: {len(files) + 1} source files')
