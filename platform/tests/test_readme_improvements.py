from datetime import datetime, timedelta, timezone

import pytest

from identity.domain import IdentityError, StaleVersion
from identity.knowledge.store import PostgresKnowledgeStore
from test_identity import build, workspace, TID, SID, OPERATOR, IP, Clock


def review_actor(name, role):
    return {'actor': name, 'actor_type': 'operator', 'roles': ['PlatformOperator', role]}


def test_knowledge_is_separate_and_requires_two_independent_reviews():
    service = build()
    created = service.create_knowledge_publication({'title': 'Disk review', 'summary': 'Verify retained capacity.',
        'body': 'Synthetic general example without a client record.'}, OPERATOR)
    assert service.store is not service.knowledge_store
    with pytest.raises(IdentityError, match='Independent'):
        service.update_knowledge_publication(created['id'], {'version': 1, 'status': 'published'}, OPERATOR)
    first = service.review_knowledge_publication(created['id'], {'version': 1, 'review': 'technical'},
        review_actor('technical-reviewer', 'KnowledgeReviewer'))
    with pytest.raises(IdentityError):
        service.review_knowledge_publication(created['id'], {'version': first['version'], 'review': 'privacy'},
            review_actor('technical-reviewer', 'PrivacyReviewer'))
    second = service.review_knowledge_publication(created['id'], {'version': first['version'], 'review': 'privacy'},
        review_actor('privacy-reviewer', 'PrivacyReviewer'))
    published = service.update_knowledge_publication(created['id'], {'version': second['version'], 'status': 'published'}, OPERATOR)
    assert service.knowledge_metrics()['active_published'] == 1
    assert service.retrieve_knowledge('azure', 'storage')['items'][0]['publication_id'] == created['id']
    with pytest.raises(IdentityError, match='immutable'):
        service.update_knowledge_publication(created['id'], {'version': published['version'], 'body': 'Changed'}, OPERATOR)


@pytest.mark.parametrize('body', ['contact alice@example.com', 'owner 11111111-1111-4111-8111-111111111111',
    'ip 10.0.0.1', 'arn:aws:ec2:private', 'secret=private', 'service.internal'])
def test_sensitive_content_is_rejected_before_knowledge_storage(body):
    service = build()
    with pytest.raises(IdentityError, match='No payload was stored'):
        service.create_knowledge_publication({'title': 'Example', 'summary': 'Generic.', 'body': body}, OPERATOR)
    assert service.knowledge_metrics()['status_counts'] == {}


def test_knowledge_cannot_use_identity_database_or_credentials():
    with pytest.raises(ValueError, match='separate databases'):
        PostgresKnowledgeStore('postgresql://knowledge_app:p@db/identity', 'postgresql://identity_app:p@db/identity')
    with pytest.raises(ValueError, match='separate runtime identity'):
        PostgresKnowledgeStore('postgresql://identity_app:p@db/knowledge', 'postgresql://identity_app:p@db/identity')


def test_rule_revision_and_parameters_are_atomic_and_strict():
    service = build()
    workspace(service)
    initial = service.list_workspace_analysis_rules(TID)
    rule = 'AZURE_DISK_UNATTACHED_RETENTION'
    updated = service.update_workspace_analysis_rules(TID, {'version': initial['version'], 'rules': [
        {'rule_id': rule, 'enabled': True, 'parameters': {'minimum_days': 21}}]}, OPERATOR)
    assert updated['version'] == initial['version'] + 1
    assert service.store.state['changes'][-1]['version'] == updated['version']
    assert service.store.state['cache_events'][-1]['directory'] is True
    assert next(r for r in updated['items'] if r['id'] == rule)['parameters']['minimum_days'] == 21
    with pytest.raises(StaleVersion):
        service.update_workspace_analysis_rules(TID, {'version': initial['version'], 'rules': [{'rule_id': rule, 'enabled': False}]}, OPERATOR)
    with pytest.raises(IdentityError):
        service.update_workspace_analysis_rules(TID, {'version': updated['version'], 'rules': [{'rule_id': rule, 'enabled': 'false'}]}, OPERATOR)


def owner(service):
    customer = service.create_customer({'name': 'Client'}, OPERATOR)
    service.create_workspace({'tenant_id': TID, 'customer_id': customer['id'], 'name': 'Production',
        'plan_tier': 'GROWTH'}, OPERATOR, scopes={'subscription_ids': [SID]})
    bootstrap = service.issue_bootstrap_key(customer['id'], {'tenant_id': TID}, OPERATOR)
    claim = service.claim_customer({'key': bootstrap['secret'], 'idp_issuer': 'test', 'idp_subject': 'owner',
        'display_name': 'Owner'}, None)
    return service.customer_context_from_key(claim['secret'], IP, 'gateway'), claim


def test_scoped_owner_key_cannot_delegate_unrestricted_access():
    service = build()
    grant, claim = owner(service)
    expiry = (service.now() + timedelta(days=1)).isoformat()
    payload = {'name': 'Restricted admin', 'roles': ['TenantAdmin'], 'all_providers': True,
               'scope_restrictions': {'azure': [SID]}, 'expires_at': expiry}
    limited = service.issue_customer_workspace_key(TID, payload, grant)
    restricted = service.customer_context_from_key(limited['secret'], IP, 'gateway')
    with pytest.raises(IdentityError) as error:
        service.issue_customer_workspace_key(TID, {**payload, 'scope_restrictions': None}, restricted)
    assert error.value.status == 403


def test_membership_downgrade_changes_existing_key_grants():
    service = build()
    grant, claim = owner(service)
    with service.store.transaction() as tx:
        tx.upsert_workspace_membership(TID, claim['user']['user_id'],
            {'roles': ['Viewer'], 'updated_at': service.now(), 'updated_by': 'operator'})
    verified = service.verify(claim['secret'], IP, 'gateway')
    assert verified['roles'] == ['Viewer']


@pytest.mark.parametrize('role', ['KnowledgeReviewer', 'PrivacyReviewer'])
def test_dedicated_reviewers_cannot_read_customer_directory_or_change_plans(role, monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from identity.auth import OperatorAuth
    auth = OperatorAuth(mode='operator_key')
    monkeypatch.setattr(auth, 'authenticate', lambda token: {'actor': 'reviewer', 'roles': [role]})
    app = FastAPI()
    dependency = auth.dependency()
    @app.get('/admin/v1/customers')
    @app.get('/admin/v1/knowledge/publications')
    @app.post('/admin/v1/knowledge/publications/item/review')
    @app.post('/admin/v1/plans')
    def guarded(actor=Depends(dependency)):
        return {'ok': True}
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer offline'}
        assert client.get('/admin/v1/knowledge/publications', headers=headers).status_code == 200
        assert client.post('/admin/v1/knowledge/publications/item/review', headers=headers).status_code == 200
        assert client.get('/admin/v1/customers', headers=headers).status_code == 403
        assert client.post('/admin/v1/plans', headers=headers).status_code == 403
