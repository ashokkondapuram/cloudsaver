"""Create fresh local demo settings without overwriting an existing .env."""
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / '.env'
key = secrets.token_hex(32)
content = '\n'.join([
    'CLOUDSAVER_MODE=demo', 'CLOUDSAVER_TENANTS=[]',
    'DEMO_ACCESS_KEY=' + key,
    'POSTGRES_PASSWORD=' + secrets.token_hex(32),
    'CLOUDSAVER_DB_PASSWORD=' + secrets.token_hex(32),
    'CLOUDSAVER_NOTIFICATION_WEBHOOK=', '',
])
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('An .env already exists; review it manually. No file was changed.')
with os.fdopen(descriptor, 'w') as stream:
    stream.write(content)
print('Created local demo configuration. Keep .env private; never upload or commit it.')
print('Start with: docker compose up --build -d')
print('Dashboard: http://127.0.0.1:3000')
print('Workspace access key: ' + key)
