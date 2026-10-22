"""Create fresh local azure workspace settings without overwriting an existing .env."""
import hashlib
import json
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / '.env'
key = secrets.token_hex(32)
tenant_id = '11111111-1111-4111-8111-111111111111'
# Replace every scope below with your authorized cloud identities before live scans.
tenants = [{
    'tenant_id': tenant_id,
    'name': 'Local workspace',
    'plan_tier': 'ENTERPRISE',
    'subscription_ids': ['22222222-2222-4222-8222-222222222222'],
    'api_key_sha256': hashlib.sha256(key.encode()).hexdigest(),
    'aws_accounts': [{
        'account_id': '123456789012',
        'region': 'us-east-1',
        'credential_profile': 'default',
    }],
    'gcp_projects': [{
        'project_id': 'customer-project',
        'regions': ['us-central1'],
    }],
    'kubernetes_clusters': [{
        'cluster_id': 'customer-cluster',
        'prometheus_url': 'https://prometheus.example.com',
        'bearer_token_env': 'CLOUDSAVER_PROMETHEUS_TOKEN_PRIMARY',
    }],
}]
content = '\n'.join([
    'CLOUDSAVER_MODE=azure',
    f'CLOUDSAVER_TENANTS={json.dumps(tenants)}',
    'POSTGRES_PASSWORD=' + secrets.token_hex(32),
    'CLOUDSAVER_DB_PASSWORD=' + secrets.token_hex(32),
    'CLOUDSAVER_NOTIFICATION_WEBHOOK=',
    'CLOUDSAVER_SCHEDULED_SCANS=true',
    'CLOUDSAVER_SCAN_INTERVAL_SECONDS=3600',
    'CLOUDSAVER_AUTOMATED_ALERTS=false',
    'AZURE_CLIENT_ID=',
    'AZURE_CLIENT_SECRET=',
    '',
])
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('An .env already exists; review it manually. No file was changed.')
with os.fdopen(descriptor, 'w') as stream:
    stream.write(content)
print('Created local ENTERPRISE workspace with Azure, AWS, GCP and Kubernetes scopes.')
print('Start with: docker compose up --build -d')
print('Optional scheduled workers: docker compose --profile scheduled up -d')
print('Dashboard: http://127.0.0.1:3000')
print('Workspace access key: ' + key)
print('Edit CLOUDSAVER_TENANTS with real subscription, account, project and cluster IDs.')
print('Mount cloud credentials via compose.override.example.yaml on scanner-service.')
