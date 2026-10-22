"""Start a loopback-only demo without writing an access key to disk."""
import os
import secrets
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
key = secrets.token_urlsafe(32)
environment.update(CLOUDSAVER_MODE='demo', DEMO_ACCESS_KEY=key, CLOUDSAVER_TENANTS='[]')
print('\nCloudSaver local demo: http://127.0.0.1:8000', flush=True)
print('Workspace access key (paste in dashboard): ' + key + '\n', flush=True)
subprocess.run([sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory',
                '--host', '127.0.0.1', '--port', '8000'], cwd=root, env=environment, check=True)
