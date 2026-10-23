"""Create the platform's local settings (platform/.env).

  python3 scripts/setup_platform.py                          create a new platform/.env (never overwrites)
  python3 scripts/setup_platform.py --migrate-from ../.env   move platform values from a CloudSaver 1.2 .env
  python3 scripts/setup_platform.py --add-callers ../.env    allow CloudSaver's service tokens to call identity-service

Secrets are generated locally and written only to the untracked platform/.env with mode 0600. Values are never
printed, except the operator access key of a new install, which is shown once. --add-callers reads CloudSaver's
CLOUDSAVER_IDENTITY_TOKEN_* values and stores only their SHA-256 digests.
"""
import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / '.env'
CLOUDSAVER_CALLERS = ('gateway', 'tenant', 'scanner', 'analytics', 'notification')
MIGRATED = {
    'TOKEN_DB_PASSWORD': 'PLATFORM_DB_PASSWORD',
    'IDENTITY_DB_OWNER_PASSWORD': 'PLATFORM_DB_OWNER_PASSWORD',
    'IDENTITY_DB_APP_PASSWORD': 'PLATFORM_DB_APP_PASSWORD',
    'CLOUDSAVER_KEY_PEPPER': 'PLATFORM_KEY_PEPPER',
    'CLOUDSAVER_KEY_PEPPER_VERSION': 'PLATFORM_KEY_PEPPER_VERSION',
    'CLOUDSAVER_KEY_PEPPER_PREVIOUS': 'PLATFORM_KEY_PEPPER_PREVIOUS',
    'CLOUDSAVER_KEYVAULT_URL': 'PLATFORM_KEYVAULT_URL',
    'CLOUDSAVER_IDENTITY_CALLERS': 'PLATFORM_IDENTITY_CALLERS',
    'CLOUDSAVER_IDENTITY_TOKEN_PORTAL': 'PLATFORM_PORTAL_TOKEN',
    'CLOUDSAVER_OPERATOR_KEY_SHA256': 'PLATFORM_OPERATOR_KEY_SHA256',
    'CLOUDSAVER_PORTAL_AUTH': 'PLATFORM_PORTAL_AUTH',
    'CLOUDSAVER_ENVIRONMENT': 'PLATFORM_ENVIRONMENT',
    'CLOUDSAVER_PROVIDER_SCOPED_KEYS': 'PLATFORM_PROVIDER_SCOPED_KEYS',
}
REQUIRED = ('PLATFORM_DB_PASSWORD', 'PLATFORM_DB_OWNER_PASSWORD', 'PLATFORM_DB_APP_PASSWORD',
            'PLATFORM_KEY_PEPPER', 'PLATFORM_IDENTITY_CALLERS', 'PLATFORM_PORTAL_TOKEN')


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def parse(file):
    values = {}
    for line in Path(file).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            name, value = line.split('=', 1)
            values[name.strip()] = value
    return values


def write_new(lines):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('platform/.env already exists. Review it manually. No file was changed.')
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')


def replace(lines):
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')
    os.replace(temporary, path)


def defaults():
    return ['PLATFORM_BILLING_ENABLED=true', 'PLATFORM_BILLING_PROVIDER=manual',
            '# Stripe stays off until both values are set and PLATFORM_BILLING_PROVIDER=stripe.',
            'PLATFORM_STRIPE_SECRET_KEY=', 'PLATFORM_STRIPE_WEBHOOK_SECRET=', 'PLATFORM_PUBLIC_URL=http://127.0.0.1:3100']


def create():
    operator_key = secrets.token_urlsafe(32)
    portal = secrets.token_urlsafe(32)
    lines = [
        'PLATFORM_DB_PASSWORD=' + secrets.token_hex(32),
        'PLATFORM_DB_OWNER_PASSWORD=' + secrets.token_hex(32),
        'PLATFORM_DB_APP_PASSWORD=' + secrets.token_hex(32),
        'PLATFORM_KEY_PEPPER=' + secrets.token_hex(32),
        'PLATFORM_KEY_PEPPER_VERSION=1',
        'PLATFORM_ENVIRONMENT=development',
        'PLATFORM_PORTAL_AUTH=operator_key',
        'PLATFORM_OPERATOR_KEY_SHA256=' + digest(operator_key),
        'PLATFORM_PORTAL_TOKEN=' + portal,
        '# SHA-256 digests only. Add CloudSaver callers with --add-callers.',
        'PLATFORM_IDENTITY_CALLERS=' + json.dumps({'portal': digest(portal)}, separators=(',', ':')),
        'PLATFORM_PROVIDER_SCOPED_KEYS=true',
    ] + defaults()
    write_new(lines)
    print('Created platform/.env.')
    print('Next: python3 scripts/setup_platform.py --add-callers ../.env (after CloudSaver has its service tokens),')
    print('then: docker compose up --build -d, and sign in to the portal at http://127.0.0.1:3100.')
    print('Operator access key (shown once): ' + operator_key)


def migrate(source):
    old = parse(source)
    lines = ['# Moved from the CloudSaver .env by setup_platform.py --migrate-from']
    moved = []
    for old_name, new_name in MIGRATED.items():
        if old.get(old_name):
            lines.append(f'{new_name}={old[old_name]}')
            moved.append(new_name)
    missing = [name for name in REQUIRED if name not in moved]
    if missing:
        raise SystemExit('The source .env is missing values for: ' + ', '.join(missing) + '. No file was changed.')
    write_new(lines + defaults())
    print('Created platform/.env with: ' + ', '.join(moved))
    print('The key pepper and operator key are unchanged, so existing keys and portal sign-in keep working.')


def add_callers(source):
    if not path.exists():
        raise SystemExit('Create platform/.env first. No file was changed.')
    tokens = parse(source)
    lines = path.read_text().splitlines()
    index = next((i for i, line in enumerate(lines) if line.startswith('PLATFORM_IDENTITY_CALLERS=')), None)
    callers = json.loads(lines[index].split('=', 1)[1]) if index is not None else {}
    added = []
    for caller in CLOUDSAVER_CALLERS:
        token = tokens.get('CLOUDSAVER_IDENTITY_TOKEN_' + caller.upper())
        if token and callers.get(caller) != digest(token):
            callers[caller] = digest(token)
            added.append(caller)
    if not added:
        print('The CloudSaver callers are already allowed. No file was changed.')
        return
    entry = 'PLATFORM_IDENTITY_CALLERS=' + json.dumps(callers, separators=(',', ':'))
    if index is None:
        lines.append(entry)
    else:
        lines[index] = entry
    replace(lines)
    print('Allowed callers: ' + ', '.join(added) + '. Apply with: docker compose up -d identity-service')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--migrate-from', metavar='ENV_FILE')
    group.add_argument('--add-callers', metavar='ENV_FILE')
    args = parser.parse_args()
    if args.migrate_from:
        migrate(args.migrate_from)
    elif args.add_callers:
        add_callers(args.add_callers)
    else:
        create()
