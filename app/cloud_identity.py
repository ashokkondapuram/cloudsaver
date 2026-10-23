"""Keyless cloud credentials rooted in one Azure managed identity."""
import os
import re
import threading
from uuid import UUID

GCP_SCOPES = ['https://www.googleapis.com/auth/cloud-platform.read-only']
TOKEN_EXCHANGE = 'api://AzureADTokenExchange'
WORKLOAD_PROVIDER = r'//iam\.googleapis\.com/projects/[0-9]{1,20}/locations/global/workloadIdentityPools/[a-z0-9-]{4,32}/providers/[a-z0-9-]{4,32}'


class CredentialError(RuntimeError):
    """Sanitized identity configuration or token failure."""


def identity_mode():
    mode = os.getenv('CLOUDSAVER_CLOUD_IDENTITY', 'managed_identity')
    if mode not in ('managed_identity', 'developer'):
        raise CredentialError('CLOUDSAVER_CLOUD_IDENTITY must be managed_identity or developer.')
    return mode


def _cfg(settings, tenant=None):
    if settings is not None:
        return settings
    from app.resource_access import runtime_settings
    return runtime_settings(tenant)


def azure_access(settings=None):
    access = _cfg(settings).get('azure_access') or os.getenv('CLOUDSAVER_AZURE_ACCESS', 'federated')
    if access not in ('federated', 'direct'):
        raise CredentialError('CLOUDSAVER_AZURE_ACCESS must be federated or direct.')
    return access


def _uuid(value, message):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        raise CredentialError(message) from None


_identity_lock = threading.Lock()
_identity_by_client = {}


def _managed_identity(client_id=None):
    """Resource-access identity; bootstrap AZURE_CLIENT_ID is used only when no platform value exists."""
    key = client_id or ''
    with _identity_lock:
        current = _identity_by_client.get(key)
        if current is not None and current[0] == key:
            return current[1]
        from azure.identity import ManagedIdentityCredential
        if current is not None:
            current[1].close()
        options = {'client_id': _uuid(client_id, 'AZURE_CLIENT_ID must be the managed identity client ID.')} if client_id else {}
        credential = ManagedIdentityCredential(**options)
        _identity_by_client[key] = (key, credential)
        return credential


def managed_identity_token(audience, settings=None, tenant=None):
    try:
        cfg = _cfg(settings, tenant)
        client_id = cfg.get('managed_identity_client_id')
        return _managed_identity(client_id).get_token(audience.rstrip('/') + '/.default').token
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The managed identity token is unavailable.') from None


def azure_credential(tenant, settings=None):
    tenant_id = _uuid(tenant['tenant_id'], 'Invalid customer tenant ID.')
    cfg = _cfg(settings, tenant)
    try:
        if identity_mode() == 'developer':
            from azure.identity import AzureCliCredential
            return AzureCliCredential(tenant_id=tenant_id, process_timeout=30)
        if azure_access(cfg) == 'direct':
            from azure.identity import ManagedIdentityCredential
            client_id = cfg.get('managed_identity_client_id')
            return ManagedIdentityCredential(**({'client_id': client_id} if client_id else {}))
        app_id = (tenant.get('identity') or {}).get('azure_app_client_id') or cfg.get('azure_app_client_id') or ''
        app_id = _uuid(app_id, 'Set CLOUDSAVER_AZURE_APP_CLIENT_ID or a workspace Azure app client ID.')
        from azure.identity import ClientAssertionCredential
        audience = cfg.get('aws_token_audience') or TOKEN_EXCHANGE
        return ClientAssertionCredential(tenant_id=tenant_id, client_id=app_id,
                                         func=lambda: managed_identity_token(audience, cfg, tenant))
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The Azure credential could not be initialized.') from None


def platform_credential():
    """Bootstrap identity for Key Vault, AI Foundry and service tokens."""
    try:
        if identity_mode() == 'developer':
            from azure.identity import AzureCliCredential
            return AzureCliCredential(process_timeout=30)
        from azure.identity import ManagedIdentityCredential
        client_id = os.getenv('AZURE_CLIENT_ID') or None
        options = {'client_id': _uuid(client_id, 'AZURE_CLIENT_ID must be the managed identity client ID.')} if client_id else {}
        return ManagedIdentityCredential(**options)
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The platform credential could not be initialized.') from None


def _assume(sts, source, session_name):
    options = {'RoleArn': source['role_arn'], 'RoleSessionName': session_name, 'DurationSeconds': 3600}
    if source.get('external_id'):
        options['ExternalId'] = source['external_id']
    return sts.assume_role(**options)['Credentials']


def aws_session(source, settings=None, tenant=None):
    import boto3
    from botocore.config import Config
    cfg = _cfg(settings, tenant)
    region, session_name = source['region'], 'cloudsaver-scan'
    if not source.get('role_arn'):
        raise CredentialError('The AWS account requires a reader role ARN.')
    config = Config(connect_timeout=10, read_timeout=30, retries={'max_attempts': 3, 'mode': 'standard'})
    clients = []
    try:
        if identity_mode() == 'developer':
            sts = boto3.Session(region_name=region).client('sts', config=config)
            clients.append(sts)
            credentials = _assume(sts, source, session_name)
        else:
            hub = cfg.get('aws_hub_role_arn') or ''
            if not re.fullmatch(r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}', hub):
                raise CredentialError('Set CLOUDSAVER_AWS_HUB_ROLE_ARN to the CloudSaver hub role.')
            token = managed_identity_token(cfg.get('aws_token_audience') or TOKEN_EXCHANGE, cfg, tenant)
            sts = boto3.Session(region_name=region).client('sts', config=config)
            clients.append(sts)
            hub_credentials = sts.assume_role_with_web_identity(
                RoleArn=hub, RoleSessionName=session_name, WebIdentityToken=token, DurationSeconds=3600)['Credentials']
            chained = boto3.Session(aws_access_key_id=hub_credentials['AccessKeyId'],
                                    aws_secret_access_key=hub_credentials['SecretAccessKey'],
                                    aws_session_token=hub_credentials['SessionToken'],
                                    region_name=region).client('sts', config=config)
            clients.append(chained)
            credentials = _assume(chained, source, session_name)
        return boto3.Session(aws_access_key_id=credentials['AccessKeyId'],
                             aws_secret_access_key=credentials['SecretAccessKey'],
                             aws_session_token=credentials['SessionToken'], region_name=region)
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The AWS reader role could not be assumed.') from None
    finally:
        for client in clients:
            client.close()


def gcp_credentials(source, *, scopes=None, settings=None, tenant=None):
    account = source.get('service_account')
    scopes = GCP_SCOPES if scopes is None else scopes
    cfg = _cfg(settings, tenant)
    try:
        if identity_mode() == 'developer':
            import google.auth
            from google.auth import impersonated_credentials
            base, _ = google.auth.default(scopes=scopes)
            if not account:
                return base
            return impersonated_credentials.Credentials(source_credentials=base, target_principal=account,
                                                        target_scopes=scopes, lifetime=3600)
        provider = cfg.get('gcp_workload_provider') or ''
        if not re.fullmatch(WORKLOAD_PROVIDER, provider):
            raise CredentialError('Set CLOUDSAVER_GCP_WORKLOAD_PROVIDER to the workload identity provider resource name.')
        if not account:
            raise CredentialError('The GCP project requires a reader service account.')
        from google.auth import identity_pool
        audience = cfg.get('gcp_token_audience') or TOKEN_EXCHANGE

        class ManagedIdentitySupplier(identity_pool.SubjectTokenSupplier):
            def get_subject_token(self, context, request):
                return managed_identity_token(audience, cfg, tenant)

        return identity_pool.Credentials(
            audience=provider, subject_token_type='urn:ietf:params:oauth:token-type:jwt',
            token_url='https://sts.googleapis.com/v1/token', subject_token_supplier=ManagedIdentitySupplier(),
            service_account_impersonation_url=f'https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{account}:generateAccessToken',
            scopes=scopes)
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The GCP workload identity credential could not be initialized.') from None


def _commands(tenant, resolved):
    tenant_id = (tenant or {}).get('tenant_id')
    commands = {'azure': [], 'aws': [], 'gcp': []}
    access = resolved.get('azure_access') or 'federated'
    app_id = (tenant or {}).get('identity', {}).get('azure_app_client_id') or resolved.get('azure_app_client_id')
    assignee = resolved.get('managed_identity_client_id') if access == 'direct' else app_id
    for sid in (tenant or {}).get('subscription_ids') or []:
        if assignee:
            commands['azure'].append(
                f'az role assignment create --assignee {assignee} --role Reader --scope /subscriptions/{sid}')
    hub = resolved.get('aws_hub_role_arn')
    if hub and tenant_id:
        commands['aws'].append(
            '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":"' + hub + '"},'
            '"Action":"sts:AssumeRole","Condition":{"StringEquals":{"sts:ExternalId":"' + tenant_id + '"}}}]}')
    for account in (tenant or {}).get('aws_accounts') or []:
        commands['aws'].append(
            f'aws iam attach-role-policy --role-name {account["role_arn"].split("/")[-1]} --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess')
    sa = (tenant or {}).get('identity', {}).get('gcp_service_account')
    for project in (tenant or {}).get('gcp_projects') or []:
        if sa:
            commands['gcp'].append(
                f'gcloud projects add-iam-policy-binding {project["project_id"]} --member serviceAccount:{sa} --role roles/viewer')
    return commands


def onboarding(tenant=None, platform=None):
    from app.resource_access import resolve, resolved_values
    mapping = resolve(platform, (tenant or {}).get('identity'))
    values = resolved_values(platform, (tenant or {}).get('identity'))
    identity = (tenant or {}).get('identity') or {}
    return {
        'aws_external_id': (tenant or {}).get('tenant_id'),
        'gcp_service_account': identity.get('gcp_service_account'),
        'identity_mode': os.getenv('CLOUDSAVER_CLOUD_IDENTITY', 'managed_identity'),
        'azure_access': values.get('azure_access'),
        'azure_app_client_id': values.get('azure_app_client_id'),
        'managed_identity_client_id': values.get('managed_identity_client_id'),
        'aws_hub_role_arn': values.get('aws_hub_role_arn'),
        'aws_token_audience': values.get('aws_token_audience'),
        'gcp_workload_provider': values.get('gcp_workload_provider'),
        'gcp_token_audience': values.get('gcp_token_audience'),
        'source': {key: mapping[key]['source'] for key in mapping},
        'commands': _commands(tenant, values),
        'setup_guide_path': 'docs/MANAGED_IDENTITY_ROLES.md',
    }


def close_providers():
    global _identity_by_client
    with _identity_lock:
        for _, credential in _identity_by_client.values():
            try:
                credential.close()
            except Exception:
                pass
        _identity_by_client = {}
