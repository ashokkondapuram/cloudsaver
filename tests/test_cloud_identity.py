import sys
import types

import pytest

from app import cloud_identity
from app.cloud_identity import CredentialError

TID = '11111111-1111-4111-8111-111111111111'
APP = '55555555-5555-4555-8555-555555555555'
HUB = 'arn:aws:iam::999999999999:role/CloudSaverHub'
ROLE = 'arn:aws:iam::123456789012:role/CloudSaverReader'
PROVIDER = '//iam.googleapis.com/projects/123456/locations/global/workloadIdentityPools/cloudsaver/providers/azure-mi'
ACCOUNT = 'reader-sa@customer-project.iam.gserviceaccount.com'


@pytest.fixture(autouse=True)
def managed(monkeypatch):
    for name in ('CLOUDSAVER_AZURE_APP_CLIENT_ID', 'CLOUDSAVER_AWS_HUB_ROLE_ARN', 'CLOUDSAVER_GCP_WORKLOAD_PROVIDER',
                 'AZURE_CLIENT_ID', 'CLOUDSAVER_AZURE_ACCESS'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('CLOUDSAVER_CLOUD_IDENTITY', 'managed_identity')
    monkeypatch.setattr(cloud_identity, 'managed_identity_token', lambda audience, *a, **k: 'mi-token-for-' + audience)


def test_azure_uses_federated_app_assertion_not_a_secret(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AZURE_APP_CLIENT_ID', APP)
    credential = cloud_identity.azure_credential({'tenant_id': TID})
    assert type(credential).__name__ == 'ClientAssertionCredential'
    assert credential._func() == 'mi-token-for-api://AzureADTokenExchange'


def test_workspace_app_override_and_missing_app():
    credential = cloud_identity.azure_credential({'tenant_id': TID, 'identity': {'azure_app_client_id': APP}})
    assert type(credential).__name__ == 'ClientAssertionCredential'
    with pytest.raises(CredentialError):
        cloud_identity.azure_credential({'tenant_id': TID})


class Sts:
    calls = []

    def __init__(self, keys):
        self.keys = keys

    def assume_role_with_web_identity(self, **options):
        self.calls.append(('web', self.keys, options))
        return {'Credentials': {'AccessKeyId': 'hub', 'SecretAccessKey': 'hub-secret', 'SessionToken': 'hub-token'}}

    def assume_role(self, **options):
        self.calls.append(('assume', self.keys, options))
        return {'Credentials': {'AccessKeyId': 'reader', 'SecretAccessKey': 'reader-secret', 'SessionToken': 'reader-token'}}

    def close(self):
        pass


def fake_boto3(monkeypatch):
    Sts.calls = []

    class Session:
        def __init__(self, **options):
            self.options = options

        def client(self, name, config=None):
            return Sts(self.options.get('aws_access_key_id'))

    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(Session=Session))


def test_aws_chains_managed_identity_through_hub_with_tenant_external_id(monkeypatch):
    fake_boto3(monkeypatch)
    source = {'region': 'us-east-1', 'role_arn': ROLE, 'external_id': TID}
    with pytest.raises(CredentialError):
        cloud_identity.aws_session(source)
    monkeypatch.setenv('CLOUDSAVER_AWS_HUB_ROLE_ARN', HUB)
    session = cloud_identity.aws_session(source)
    assert session.options['aws_access_key_id'] == 'reader'
    web, assume = Sts.calls
    assert web[2]['RoleArn'] == HUB and web[2]['WebIdentityToken'].startswith('mi-token-for-')
    assert assume[1] == 'hub' and assume[2]['RoleArn'] == ROLE and assume[2]['ExternalId'] == TID


def test_aws_developer_mode_uses_default_chain_then_role(monkeypatch):
    fake_boto3(monkeypatch)
    monkeypatch.setenv('CLOUDSAVER_CLOUD_IDENTITY', 'developer')
    cloud_identity.aws_session({'region': 'us-east-1', 'role_arn': ROLE, 'external_id': TID})
    assert [c[0] for c in Sts.calls] == ['assume'] and Sts.calls[0][1] is None


def test_gcp_uses_workload_identity_federation(monkeypatch):
    source = {'project_id': 'customer-project', 'service_account': ACCOUNT}
    with pytest.raises(CredentialError):
        cloud_identity.gcp_credentials(source)
    monkeypatch.setenv('CLOUDSAVER_GCP_WORKLOAD_PROVIDER', PROVIDER)
    with pytest.raises(CredentialError):
        cloud_identity.gcp_credentials({'project_id': 'customer-project'})
    credentials = cloud_identity.gcp_credentials(source)
    assert type(credentials).__name__ == 'Credentials'
    assert credentials.service_account_email == ACCOUNT
    assert credentials._subject_token_supplier.get_subject_token(None, None).startswith('mi-token-for-')


def test_onboarding_exposes_only_identifiers(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_AWS_HUB_ROLE_ARN', HUB)
    values = cloud_identity.onboarding({'tenant_id': TID, 'identity': {'gcp_service_account': ACCOUNT}})
    assert values['aws_external_id'] == TID and values['aws_hub_role_arn'] == HUB
    assert values['gcp_service_account'] == ACCOUNT
    assert not any('secret' in key for key in values)
