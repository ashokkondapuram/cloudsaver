"""BigQuery billing export query pagination (jobs.query pageToken continuations)."""
from datetime import date

import pytest

from app.collectors import billing_sync


def _row(day, billed='1', effective='1', kind='regular', resource=None):
    return {'f': [{'v': v} for v in [day, 'USD', kind, resource, billed, effective]]}


def _binding(**extra):
    base = dict(
        provider='gcp',
        scope_id='test-project',
        billing_project='billing-project',
        dataset='billing',
        table='export',
    )
    base.update(extra)
    return base


class Credential:
    token = 'synthetic'

    def refresh(self, request):
        pass


def _tenant():
    return dict(
        tenant_id='00000000-0000-4000-8000-000000000001',
        gcp_projects=[dict(project_id='test-project')],
    )


def test_gcp_billing_merges_multi_page_query_results(monkeypatch):
    pages = []

    def post(url, token, body, scope_id=None):
        assert token == 'synthetic'
        pages.append(('post', body.get('maxResults')))
        return dict(
            jobComplete=True,
            totalRows='2',
            jobReference={'projectId': 'billing-project', 'jobId': 'job_page_test'},
            pageToken='token-page-2',
            rows=[_row('2026-10-01', '10', '8')],
        )

    def get_results(project, job_id, token, page_token):
        assert project == 'billing-project' and job_id == 'job_page_test' and token == 'synthetic'
        pages.append(('get', page_token))
        return dict(jobComplete=True, rows=[_row('2026-10-02', '3', '2')])

    monkeypatch.setattr(billing_sync, '_post', post)
    monkeypatch.setattr(billing_sync, '_bq_get_query_results', get_results)
    monkeypatch.setattr('app.cloud_identity.gcp_credentials', lambda *a, **k: Credential())

    rows, grain, _ = billing_sync.gcp_rows(_binding(), _tenant(), date(2026, 10, 1), date(2026, 10, 3))
    assert grain == 'project'
    assert [r['day'].isoformat() for r in rows] == ['2026-10-01', '2026-10-02']
    assert rows[0]['billed'] == '10' and rows[1]['effective'] == '2'
    assert pages == [('post', billing_sync.MAX_ROWS), ('get', 'token-page-2')]


def test_gcp_billing_rejects_page_token_without_job_id(monkeypatch):
    monkeypatch.setattr(
        billing_sync,
        '_post',
        lambda *a, **k: dict(jobComplete=True, totalRows='1', pageToken='orphan', rows=[_row('2026-10-01')]),
    )
    monkeypatch.setattr('app.cloud_identity.gcp_credentials', lambda *a, **k: Credential())
    with pytest.raises(ValueError, match='incomplete'):
        billing_sync.gcp_rows(_binding(), _tenant(), date(2026, 10, 1), date(2026, 10, 2))


def test_gcp_billing_rejects_repeated_page_token(monkeypatch):
    monkeypatch.setattr(
        billing_sync,
        '_post',
        lambda *a, **k: dict(
            jobComplete=True,
            totalRows='1',
            jobReference={'jobId': 'job_repeat'},
            pageToken='same-token',
            rows=[_row('2026-10-01')],
        ),
    )

    def get_results(project, job_id, token, page_token):
        return dict(jobComplete=True, pageToken='same-token', rows=[_row('2026-10-02')])

    monkeypatch.setattr(billing_sync, '_bq_get_query_results', get_results)
    monkeypatch.setattr('app.cloud_identity.gcp_credentials', lambda *a, **k: Credential())
    with pytest.raises(ValueError, match='pagination cursor'):
        billing_sync.gcp_rows(_binding(), _tenant(), date(2026, 10, 1), date(2026, 10, 3))


def test_gcp_billing_pagination_page_bound(monkeypatch):
    monkeypatch.setattr(
        billing_sync,
        '_post',
        lambda *a, **k: dict(
            jobComplete=True,
            totalRows='1',
            jobReference={'jobId': 'job_bound'},
            pageToken='page-0',
            rows=[_row('2026-10-01')],
        ),
    )
    counter = {'n': 0}

    def get_results(project, job_id, token, page_token):
        counter['n'] += 1
        return dict(jobComplete=True, pageToken=f'page-{counter["n"]}', rows=[_row('2026-10-02')])

    monkeypatch.setattr(billing_sync, '_bq_get_query_results', get_results)
    monkeypatch.setattr('app.cloud_identity.gcp_credentials', lambda *a, **k: Credential())
    with pytest.raises(ValueError, match='pagination limit'):
        billing_sync.gcp_rows(_binding(), _tenant(), date(2026, 10, 1), date(2026, 10, 3))
