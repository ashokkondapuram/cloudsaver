"""Generate/check SHA-256 inventory from exact tracked release bytes; excludes the manifest itself."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def inventory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    files=[]
    for name in sorted(filter(None,subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'))):
        if name=='RELEASE_MANIFEST.json':continue
        path=ROOT/name
        if not path.is_file() or path.is_symlink():raise ValueError('Manifest requires regular tracked source files')
        raw=path.read_bytes();files.append(dict(path=name,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)))
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    heads={}
    for name,config in [('core','alembic.ini'),('identity','platform/identity_alembic.ini')]:
        cfg=Config(str(ROOT/config))
        if name=='core':cfg.set_main_option('script_location',str(ROOT/'migrations'))
        heads[name]=ScriptDirectory.from_config(cfg).get_current_head()
    return dict(version='1.6.0',inventory_sha256=digest,migration_heads=heads,exclusions=['RELEASE_MANIFEST.json (self-reference)'],files=files)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    expected=inventory();path=ROOT/'RELEASE_MANIFEST.json'
    if args.check:
        if json.loads(path.read_text())!=expected:raise SystemExit('Release manifest is stale. Stage all source changes, then run python scripts/release_manifest.py')
        print('Release manifest hashes, inventory and Alembic migration heads match.')
    else:path.write_text(json.dumps(expected,indent=2)+'\n')

if __name__=='__main__':main()
