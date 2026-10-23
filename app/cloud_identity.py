"""Keyless cloud credentials rooted in one Azure managed identity.

managed_identity (default, CloudSaver hosted on Azure):
  Azure  - ClientAssertionCredential for a multi-tenant app that trusts the
           managed identity through a federated identity credential.
  AWS    - AssumeRoleWithWebIdentity into a CloudSaver hub role with the managed
           identity token, then AssumeRole into the customer role with the
           tenant ID as external ID.
  GCP    - Workload Identity Federation with the managed identity token as the
           subject token, impersonating the tenant's operator-assigned service account.

developer (local only): Azure CLI, the AWS default chain (for example an SSO
profile) and gcloud application default credentials, each followed by the same
per-scope role or service-account impersonation. No mode reads stored secrets.
"""
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


def azure_access():
    access = os.getenv('CLOUDSAVER_AZURE_ACCESS', 'federated')
    if access not in ('federated', 'direct'):
        raise CredentialError('CLOUDSAVER_AZURE_ACCESS must be federated or direct.')
    return access


def _uuid(value, message):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        raise CredentialError(message) from None


_identity_lock = threading.Lock()
_identity = None


def _managed_identity():
    """One shared managed identity; AZURE_CLIENT_ID selects a user-assigned identity."""
    global _identity
    with _identity_lock:
        if _identity is None:
            from azure.identity import ManagedIdentityCredential
            client_id = os.getenv('AZURE_CLIENT_ID') or None
            options = {'client_id': _uuid(client_id, 'AZURE_CLIENT_ID must be the managed identity client ID.')} if client_id else {}
            _identity = ManagedIdentityCredential(**options)
        return _identity


def managed_identity_token(audience):
    """Short-lived token for a federation audience; never logged or cached on disk."""
    try:
        return _managed_identity().get_token(audience.rstrip('/') + '/.default').token
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The managed identity token is unavailable.') from None


def azure_credential(tenant):
    """Credential for one customer directory. The caller closes it after the scan."""
    tenant_id = _uuid(tenant['tenant_id'], 'Invalid customer tenant ID.')
    try:
        if identity_mode() == 'developer':
            from azure.identity import AzureCliCredential
            return AzureCliCredential(tenant_id=tenant_id, process_timeout=30)
        if azure_access() == 'direct':
            from azure.identity import ManagedIdentityCredential
            client_id = os.getenv('AZURE_CLIENT_ID') or None
            return ManagedIdentityCredential(**({'client_id': client_id} if client_id else {}))
        app_id = (tenant.get('identity') or {}).get('azure_app_client_id') or os.getenv('CLOUDSAVER_AZURE_APP_CLIENT_ID', '')
        app_id = _uuid(app_id, 'Set CLOUDSAVER_AZURE_APP_CLIENT_ID or a workspace Azure app client ID.')
        from azure.identity import ClientAssertionCredential
        return ClientAssertionCredential(tenant_id=tenant_id, client_id=app_id,
                                         func=lambda: managed_identity_token(TOKEN_EXCHANGE))
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The Azure credential could not be initialized.') from None


def platform_credential():
    """CloudSaver's own identity, for platform-hosted services such as the AI Foundry model. The caller closes it."""
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


def aws_session(source):
    """boto3 session with temporary credentials for one account's reader role."""
    import boto3
    from botocore.config import Config
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
            # Every tenant shares one managed identity, so customer roles must require the
            # tenant's external ID; only a chained AssumeRole through a hub can send it.
            hub = os.getenv('CLOUDSAVER_AWS_HUB_ROLE_ARN', '')
            if not re.fullmatch(r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}', hub):
                raise CredentialError('Set CLOUDSAVER_AWS_HUB_ROLE_ARN to the CloudSaver hub role.')
            token = managed_identity_token(os.getenv('CLOUDSAVER_AWS_TOKEN_AUDIENCE', TOKEN_EXCHANGE))
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


def gcp_credentials(source, *, scopes=None):
    """Google credentials that impersonate the project's reader service account."""
    account = source.get('service_account')
    scopes = GCP_SCOPES if scopes is None else scopes
    try:
        if identity_mode() == 'developer':
            import google.auth
            from google.auth import impersonated_credentials
            base, _ = google.auth.default(scopes=scopes)
            if not account:
                return base
            return impersonated_credentials.Credentials(source_credentials=base, target_principal=account,
                                                        target_scopes=scopes, lifetime=3600)
        provider = os.getenv('CLOUDSAVER_GCP_WORKLOAD_PROVIDER', '')
        if not re.fullmatch(WORKLOAD_PROVIDER, provider):
            raise CredentialError('Set CLOUDSAVER_GCP_WORKLOAD_PROVIDER to the workload identity provider resource name.')
        if not account:
            raise CredentialError('The GCP project requires a reader service account.')
        from google.auth import identity_pool
        audience = os.getenv('CLOUDSAVER_GCP_TOKEN_AUDIENCE', TOKEN_EXCHANGE)

        class ManagedIdentitySupplier(identity_pool.SubjectTokenSupplier):
            def get_subject_token(self, context, request):
                return managed_identity_token(audience)

        return identity_pool.Credentials(
            audience=provider, subject_token_type='urn:ietf:params:oauth:token-type:jwt',
            token_url='https://sts.googleapis.com/v1/token', subject_token_supplier=ManagedIdentitySupplier(),
            service_account_impersonation_url=f'https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{account}:generateAccessToken',
            scopes=scopes)
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('The GCP workload identity credential could not be initialized.') from None


def onboarding(tenant=None):
    """Non-secret values a customer needs to grant CloudSaver access."""
    identity = (tenant or {}).get('identity') or {}
    app_id = identity.get('azure_app_client_id') or os.getenv('CLOUDSAVER_AZURE_APP_CLIENT_ID') or None
    return {
        'aws_external_id': (tenant or {}).get('tenant_id'),
        'gcp_service_account': identity.get('gcp_service_account'),
        'identity_mode': os.getenv('CLOUDSAVER_CLOUD_IDENTITY', 'managed_identity'),
        'azure_access': os.getenv('CLOUDSAVER_AZURE_ACCESS', 'federated'),
        'azure_app_client_id': app_id,
        'managed_identity_client_id': os.getenv('AZURE_CLIENT_ID') or None,
        'aws_hub_role_arn': os.getenv('CLOUDSAVER_AWS_HUB_ROLE_ARN') or None,
        'aws_token_audience': os.getenv('CLOUDSAVER_AWS_TOKEN_AUDIENCE', TOKEN_EXCHANGE),
        'gcp_workload_provider': os.getenv('CLOUDSAVER_GCP_WORKLOAD_PROVIDER') or None,
    }


def close_providers():
    global _identity
    with _identity_lock:
        try:
            if _identity is not None:
                _identity.close()
        finally:
            _identity = None
