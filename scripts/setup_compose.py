"""Create fresh local settings without overwriting an existing .env.

CLOUDSAVER_TENANTS only seeds the tenant registry on first start. Afterwards,
manage workspaces in the operator console (/admin) and scopes in Settings.
"""
import hashlib
import json
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / '.env'
key = secrets.token_hex(32)
operator_key = secrets.token_urlsafe(32)
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
        'role_arn': 'arn:aws:iam::123456789012:role/CloudSaverReader',
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
    'CLOUDSAVER_OPERATOR_KEY_SHA256=' + hashlib.sha256(operator_key.encode()).hexdigest(),
    'POSTGRES_PASSWORD=' + secrets.token_hex(32),
    'CLOUDSAVER_DB_PASSWORD=' + secrets.token_hex(32),
    'CLOUDSAVER_SCHEDULED_SCANS=false',
    'CLOUDSAVER_AUTOMATED_ALERTS=false',
    '# managed_identity on Azure; developer for local sign-in (see compose.override.example.yaml).',
    'CLOUDSAVER_CLOUD_IDENTITY=developer',
    'CLOUDSAVER_INSTALL_AZURE_CLI=false',
    'AZURE_MANAGED_IDENTITY_CLIENT_ID=',
    'CLOUDSAVER_AZURE_APP_CLIENT_ID=',
    'CLOUDSAVER_AWS_HUB_ROLE_ARN=',
    'CLOUDSAVER_GCP_WORKLOAD_PROVIDER=',
    '',
])
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('An .env already exists; review it manually. No file was changed.')
with os.fdopen(descriptor, 'w') as stream:
    stream.write(content)
print('Created a local ENTERPRISE workspace with Azure, AWS, GCP and Kubernetes scopes.')
print('Start with: docker compose up --build -d')
print('Dashboard: http://127.0.0.1:3000   Operator console: http://127.0.0.1:3000/admin')
print('Workspace access key (shown once): ' + key)
print('Operator access key (shown once): ' + operator_key)
print('Replace the placeholder scopes in Settings > Cloud accounts after you sign in.')
