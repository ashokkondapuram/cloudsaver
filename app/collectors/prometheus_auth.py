"""Read-only Prometheus federation rooted in existing tenant-bound cloud identities."""
from urllib.parse import urlsplit
from app.cloud_http import JSONReader
from app.cloud_identity import azure_credential, aws_session, gcp_credentials
from app.cloud_scope import REGION, ROLE_ARN, SERVICE_ACCOUNT, matches
from app.collectors.kubernetes import token_reader
from app.scanner import ScanError


def reader(source, binding):
    backend=binding.get('telemetry_backend','prometheus_http')
    host=urlsplit(source['prometheus_url']).hostname
    if backend=='prometheus_http':
        return token_reader(source['bearer_token_env'])
    if backend=='azure_amp':
        if not host or not host.endswith('.prometheus.monitor.azure.com'):
            raise ScanError('Azure Prometheus endpoint does not match the approved cloud service')
        credential=azure_credential({'tenant_id':binding['tenant_id']})
        try:
            return JSONReader(token=credential.get_token('https://prometheus.monitor.azure.com/.default').token,timeout_seconds=15)
        finally:
            credential.close()
    if backend=='aws_amp_sigv4':
        region=binding.get('region')
        if not matches(REGION,region) or not matches(ROLE_ARN,binding.get('role_arn')) or host!='aps-workspaces.'+region+'.amazonaws.com':
            raise ScanError('AWS Prometheus endpoint or reader role is invalid')
        session=aws_session(dict(region=region,role_arn=binding['role_arn'],external_id=binding['tenant_id']))
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        def sign(url):
            if urlsplit(url).hostname!=host:
                raise ScanError('Prometheus signing destination changed')
            request=AWSRequest(method='GET',url=url)
            SigV4Auth(session.get_credentials().get_frozen_credentials(),'aps',region).add_auth(request)
            return dict(request.headers)
        return JSONReader(headers_factory=sign,timeout_seconds=15)
    if backend=='gcp_gmp':
        if host!='monitoring.googleapis.com' or not matches(SERVICE_ACCOUNT,binding.get('service_account')):
            raise ScanError('Google Prometheus endpoint or service account is invalid')
        return JSONReader(credentials=gcp_credentials({'service_account':binding['service_account']},tenant={'tenant_id':binding['tenant_id']}),timeout_seconds=15)
    raise ScanError('Unsupported Kubernetes telemetry backend')
