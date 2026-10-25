"""Create fresh CloudSaver settings, or update an existing .env for the separate platform project.

  python scripts/setup_compose.py                  create a new .env (never overwrites)
  python scripts/setup_compose.py --add-identity   add missing identity caller tokens
  python scripts/setup_compose.py --init-db-passwords fill blank DB passwords for a new database
  python scripts/setup_compose.py --cutover        make identity-service authoritative
  python scripts/setup_compose.py --prune-platform remove settings that moved to platform/.env
  python scripts/setup_compose.py --caller-digests print caller token SHA-256 digests for the platform

Secrets are generated locally and written only to the untracked .env; no command prints them. The platform
(identity-service, platform portal and their database) runs from platform/ with its own .env. Give it the caller
digests with platform/scripts/setup_platform.py --add-callers.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / '.env'
platform_env = ROOT / 'platform' / '.env'
CALLERS = ('gateway', 'tenant', 'scanner', 'analytics', 'notification', 'agent')
TOKENS = tuple('CLOUDSAVER_IDENTITY_TOKEN_' + caller.upper() for caller in CALLERS)
IDENTITY_URL = 'http://identity-service:8005'
CUTOVER = {'CLOUDSAVER_KEY_VERIFIER': 'identity', 'CLOUDSAVER_DIRECTORY_MODE': 'cutover',
           'CLOUDSAVER_PROVIDER_SCOPED_KEYS': 'true'}
PLATFORM_KEYS = ('TOKEN_DB_PASSWORD', 'IDENTITY_DB_OWNER_PASSWORD', 'IDENTITY_DB_APP_PASSWORD',
                 'CLOUDSAVER_IDENTITY_CALLERS', 'CLOUDSAVER_IDENTITY_TOKEN_PORTAL', 'CLOUDSAVER_PORTAL_AUTH',
                 'CLOUDSAVER_OPERATOR_KEY_SHA256', 'CLOUDSAVER_IDENTITY_REDIS_URL')
PLATFORM_PREFIXES = ('CLOUDSAVER_KEY_PEPPER', 'STRIPE_', 'CLOUDSAVER_STRIPE_', 'BILLING_RETURN', 'CLOUDSAVER_BILLING_RETURN')


def identity_values():
    values = {'CLOUDSAVER_IDENTITY_URL': IDENTITY_URL}
    values.update({name: secrets.token_urlsafe(32) for name in TOKENS})
    return values


def read_env(target=None):
    target = target or path
    return target.read_text().splitlines() if target.exists() else []


def write_env(lines):
    temporary = path.with_name('.env.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')
    os.replace(temporary, path)


def name_of(line):
    if '=' not in line or line.lstrip().startswith('#'):
        return None
    return line.split('=', 1)[0].strip()


def names(lines):
    return {n for n in map(name_of, lines) if n}


def values_of(lines):
    return {name_of(line): line.split('=', 1)[1] for line in lines if name_of(line)}


def digests(lines):
    """Caller name to SHA-256 hex digest, for PLATFORM_IDENTITY_CALLERS. Never the token values."""
    values = values_of(lines)
    return {caller: hashlib.sha256(values[name].encode()).hexdigest()
            for caller, name in zip(CALLERS, TOKENS) if values.get(name)}


def print_digests(lines):
    print('Caller digests for the platform (PLATFORM_IDENTITY_CALLERS): '
          + json.dumps(digests(lines), separators=(',', ':'), sort_keys=True))


def is_platform_key(name):
    return name in PLATFORM_KEYS or name.startswith(PLATFORM_PREFIXES)


def add_identity():
    lines = read_env()
    if not lines:
        raise SystemExit('No .env found; run scripts/setup_compose.py first.')
    present = values_of(lines)
    values = identity_values()
    added = [name for name in values if not present.get(name)]
    if added:
        write_env([line for line in lines if name_of(line) not in added] + ['# Identity-service in the platform project (reached over platform-link)']
                  + [f'{name}={values[name]}' for name in added])
        print('Added to .env: ' + ', '.join(added))
        lines = read_env()
    else:
        print('The identity caller settings are already present. No file was changed.')
    print_digests(lines)


def init_db_passwords():
    """Repair a copied template for first boot; never rotate a configured password.

    This only edits .env. Existing database roles require their original credentials.
    """
    if not path.exists():
        raise SystemExit('No .env found; run python3 scripts/setup_compose.py first. No file was changed.')
    lines = read_env()
    keys = ('POSTGRES_PASSWORD', 'CLOUDSAVER_DB_PASSWORD')
    for key in keys:
        if sum(name_of(line) == key for line in lines) > 1:
            raise SystemExit('Duplicate database password settings; resolve them manually. No file was changed.')
    current = values_of(lines)
    missing = [key for key in keys if key not in current or re.fullmatch(r'''(?:''|""|)\s*(?:\#.*)?''', current[key].strip())]
    if not missing:
        print('Database passwords are already configured. No file was changed.')
        return
    write_env([line for line in lines if name_of(line) not in missing]
              + [f'{key}={secrets.token_hex(32)}' for key in missing])
    print('Initialized blank database settings: ' + ', '.join(missing))
    print('New database only: this does not change passwords in an existing PostgreSQL volume.')


def cutover():
    lines = read_env()
    if not set(TOKENS) <= names(lines):
        raise SystemExit('Run scripts/setup_compose.py --add-identity first.')
    kept = [line for line in lines if name_of(line) not in CUTOVER]
    write_env(kept + [f'{k}={v}' for k, v in CUTOVER.items()])
    print('Set ' + ', '.join(f'{k}={v}' for k, v in CUTOVER.items()))
    print('Apply with: docker compose --profile scheduled up --build -d')


def prune_platform():
    if 'PLATFORM_KEY_PEPPER' not in names(read_env(platform_env)):
        raise SystemExit('platform/.env with PLATFORM_KEY_PEPPER is required before platform settings are removed '
                         'from .env. Run platform/scripts/setup_platform.py first. No file was changed.')
    lines = read_env()
    removed = [n for n in map(name_of, lines) if n and is_platform_key(n)]
    if not removed:
        print('No platform settings found in .env. No file was changed.')
        return
    write_env([line for line in lines if not (name_of(line) and is_platform_key(name_of(line)))])
    print('Removed from .env: ' + ', '.join(removed))


def create():
    lines = [
        'CLOUDSAVER_MODE=azure',
        # A fresh stack starts empty; customers, workspaces and keys are managed in the platform portal.
        'CLOUDSAVER_TENANTS=[]',
        'POSTGRES_PASSWORD=' + secrets.token_hex(32),
        'CLOUDSAVER_DB_PASSWORD=' + secrets.token_hex(32),
        'CLOUDSAVER_SCHEDULED_SCANS=false',
        'CLOUDSAVER_AUTOMATED_ALERTS=false',
        'CLOUDSAVER_ENVIRONMENT=development',
        '# managed_identity on Azure; developer = local CLI/SSO sign-in (see README.md).',
        'CLOUDSAVER_CLOUD_IDENTITY=developer',
        'CLOUDSAVER_INSTALL_AZURE_CLI=false',
        'AZURE_MANAGED_IDENTITY_CLIENT_ID=',
        'CLOUDSAVER_AZURE_APP_CLIENT_ID=',
        'CLOUDSAVER_AWS_HUB_ROLE_ARN=',
        'CLOUDSAVER_GCP_WORKLOAD_PROVIDER=',
        '# Identity-service in the platform project (reached over platform-link)',
    ] + [f'{k}={v}' for k, v in identity_values().items()] + [f'{k}={v}' for k, v in CUTOVER.items()]
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('An .env already exists; use --add-identity or review it manually. No file was changed.')
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')
    print('Created .env with no workspaces.')
    print_digests(lines)
    print('Next: add these digests to the platform with platform/scripts/setup_platform.py --add-callers,')
    print('start the platform (make platform-up), then CloudSaver (docker compose up --build -d).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--add-identity', action='store_true')
    group.add_argument('--init-db-passwords', action='store_true',
                       help='Fill missing/blank DB passwords for a new database; preserve existing values')
    group.add_argument('--cutover', action='store_true')
    group.add_argument('--prune-platform', action='store_true')
    group.add_argument('--caller-digests', action='store_true')
    args = parser.parse_args()
    if args.add_identity:
        add_identity()
    elif args.init_db_passwords:
        init_db_passwords()
    elif args.cutover:
        cutover()
    elif args.prune_platform:
        prune_platform()
    elif args.caller_digests:
        print_digests(read_env())
    else:
        create()
