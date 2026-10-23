"""Issue a new platform operator key and store only its SHA-256 in .env.

The previous operator key stops working after the services restart.
"""
import hashlib
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / '.env'
if not path.exists():
    raise SystemExit('No .env found; run scripts/setup_compose.py first.')
key = secrets.token_urlsafe(32)
line = 'CLOUDSAVER_OPERATOR_KEY_SHA256=' + hashlib.sha256(key.encode()).hexdigest()
lines = [l for l in path.read_text().splitlines() if not l.startswith('CLOUDSAVER_OPERATOR_KEY_SHA256=')]
temporary = path.with_suffix('.tmp')
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, 'w') as stream:
    stream.write('\n'.join(lines + [line]) + '\n')
os.replace(temporary, path)
print('Operator access key (shown once): ' + key)
print('Restart the stack to apply it: docker compose up -d')
