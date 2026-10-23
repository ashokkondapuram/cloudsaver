"""Read-only resource access probes; never returns tokens or raw provider errors."""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone

from app.cloud_identity import CredentialError, TOKEN_EXCHANGE

logger = logging.getLogger('cloudsaver.access_probe')

MESSAGES = {
    'ok': 'Access is ready.',
    'not_configured': 'This provider is not configured yet.',
    'identity_unavailable': 'The managed identity token is unavailable.',
    'federation_failed': 'Federation into this provider failed.',
    'consent_required': 'Admin consent or trust is still required.',
    'access_denied': 'Access was denied for the configured scope.',
    'error': 'The access check could not be completed.',
    'unavailable': 'No scanner claimed this check in time.',
}


def _checked_at():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _row(provider, status, target=None):
    return {'provider': provider, 'status': status, 'message': MESSAGES.get(status, MESSAGES['error']),
            'checked_at': _checked_at(), 'target': target}


def _run(name, fn, timeout=10):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            return _row(name, 'error')
        except CredentialError as exc:
            text = str(exc).lower()
            if 'consent' in text:
                return _row(name, 'consent_required')
            if 'unavailable' in text:
                return _row(name, 'identity_unavailable')
            if 'denied' in text or 'forbidden' in text:
                return _row(name, 'access_denied')
            return _row(name, 'federation_failed')
        except Exception:
            logger.info('Access probe failed provider=%s', name)
            return _row(name, 'error')


def probe_managed_identity(settings):
    from app.cloud_identity import managed_identity_token
    audience = settings.get('aws_token_audience') or TOKEN_EXCHANGE
    try:
        managed_identity_token(audience)
        return _row('managed_identity', 'ok')
    except CredentialError:
        return _row('managed_identity', 'identity_unavailable')
    except Exception:
        return _row('managed_identity', 'error')


def probe_azure(tenant, settings):
    if not tenant.get('subscription_ids'):
        return _row('azure', 'not_configured')
    if settings.get('azure_access') == 'federated' and not (tenant.get('identity') or {}).get('azure_app_client_id') \
            and not settings.get('azure_app_client_id'):
        return _row('azure', 'not_configured')
    target = str(tenant['subscription_ids'][0])

    def run():
        from app.cloud_identity import azure_credential
        credential = azure_credential(tenant, settings=settings)
        try:
            token = credential.get_token('https://management.azure.com/.default').token
            if not token:
                return _row('azure', 'federation_failed', target)
            import httpx
            response = httpx.get(f'https://management.azure.com/subscriptions/{target}?api-version=2022-12-01',
                                 headers={'Authorization': 'Bearer ' + token}, timeout=10)
            # Never log response body; map status only.
            if response.status_code == 403:
                return _row('azure', 'access_denied', target)
            if response.status_code == 401:
                return _row('azure', 'consent_required', target)
            if response.status_code >= 400:
                return _row('azure', 'error', target)
            return _row('azure', 'ok', target)
        finally:
            credential.close()

    return _run('azure', run)


def probe_aws(tenant, settings):
    accounts = tenant.get('aws_accounts') or []
    if not accounts or not settings.get('aws_hub_role_arn'):
        return _row('aws', 'not_configured')
    account = accounts[0]
    target = account['account_id']

    def run():
        from app.cloud_identity import aws_session
        source = dict(account, external_id=tenant['tenant_id'])
        session = aws_session(source, settings=settings)
        session.client('sts').get_caller_identity()
        return _row('aws', 'ok', target)

    return _run('aws', run)


def probe_gcp(tenant, settings):
    projects = tenant.get('gcp_projects') or []
    service_account = (tenant.get('identity') or {}).get('gcp_service_account')
    if not projects or not service_account or not settings.get('gcp_workload_provider'):
        return _row('gcp', 'not_configured')
    project = projects[0]['project_id']

    def run():
        from app.cloud_identity import gcp_credentials
        credentials = gcp_credentials({'service_account': service_account, 'project_id': project}, settings=settings)
        credentials.refresh(None)
        return _row('gcp', 'ok', project)

    return _run('gcp', run)


def run_probe(tenant=None, platform=None, *, include_managed_identity=False):
    from app.resource_access import resolved_values
    settings = resolved_values(platform, (tenant or {}).get('identity'))
    providers = []
    if include_managed_identity or tenant is None:
        providers.append(probe_managed_identity(settings))
    if tenant is not None:
        providers.extend([probe_azure(tenant, settings), probe_aws(tenant, settings), probe_gcp(tenant, settings)])
    return {'providers': providers}
