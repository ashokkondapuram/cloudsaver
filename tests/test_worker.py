from copy import deepcopy
from uuid import uuid4

import pytest

from app.config import Settings
from workers import tasks

TENANT = '11111111-1111-4111-8111-111111111111'
SUB = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'


def settings(mode='azure'):
    return Settings(mode, 'unused.sqlite', ({'tenant_id': TENANT, 'name': 'Workspace',
                    'subscription_ids': [SUB], 'api_key_sha256': '0' * 64},), 'unused-pg')


def finding(subscription=SUB):
    return dict(rule_id='ORPHANED_DISK', severity='HIGH', resource_name='archive',
                resource_type='Microsoft.Compute/disks', resource_group='review',
                subscription_id=subscription,
                resource_id=f'/subscriptions/{subscription}/resourceGroups/review/providers/Microsoft.Compute/disks/archive',
                estimated_monthly_waste_usd=None, details='Review retention requirements')


class Repository:
    """Behavioral transaction substitute; these tests do not establish PostgreSQL RLS."""
    def __init__(self, active=None):
        self.active = [SUB] if active is None else active
        self.jobs, self.scans = {}, {}
        self.attempted_scans = []
        self.fail_completion = False

    def plan_tier(self, tenant_id):
        return 'ENTERPRISE'

    def reserve_scheduled_job(self, tenant_id, job_id, minimum):
        self.queue_job(tenant_id, job_id)
        return True

    def active_subscriptions(self, tenant_id):
        assert tenant_id == TENANT
        return list(self.active)

    def queue_job(self, tenant_id, job_id):
        assert tenant_id == TENANT
        self.jobs.setdefault(job_id, dict(status='queued', scan_id=None, attempts=0))

    def get_job(self, tenant_id, job_id):
        return self.jobs.get(job_id)

    def start_job(self, tenant_id, job_id, token):
        job = self.jobs[job_id]
        if job['status'] in ('completed', 'failed'):
            return False
        if job['attempts'] >= 4:
            job.update(status='failed', error_code='retry_limit')
            return False
        job.update(status='running', attempts=job['attempts'] + 1)
        return True

    def fail_job(self, tenant_id, job_id, error_code, final=False, token=None):
        job = self.jobs[job_id]
        if job['status'] not in ('completed', 'failed'):
            job.update(status='failed' if final else 'queued', error_code=error_code)

    def complete_job(self, tenant_id, job_id, scan, subscriptions, *, token):
        self.attempted_scans.append(deepcopy(scan))
        if not set(subscriptions) <= set(self.active) or self.fail_completion:
            raise RuntimeError('Transaction could not commit')
        self.scans[scan['scan_id']] = deepcopy(scan)
        self.jobs[job_id].update(status='completed', scan_id=scan['scan_id'])

    def mark_notification(self, tenant_id, job_id, status):
        self.jobs[job_id]['notification_status'] = status


class Lease:
    def __init__(self, available=True):
        self.available, self.released = available, False

    def acquire(self, tenant_id, token):
        assert tenant_id == TENANT
        return self.available

    def renew(self, tenant_id, token):
        return self.available

    def close(self):
        pass

    def release(self, tenant_id, token):
        self.released = True


def test_imported_schedule_is_disabled_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_SCHEDULED_SCANS', raising=False)
    monkeypatch.setattr(tasks, 'dependencies', lambda: pytest.fail('Disabled task opened dependencies'))
    assert tasks.scheduled_scan_all.run() == {'scheduled': 0, 'enabled': False}


@pytest.mark.parametrize('tenant,subscriptions', [(OTHER, [SUB]), (TENANT, [OTHER]), (TENANT, []), (TENANT, [SUB, SUB])])
def test_scope_is_checked_before_scanning(tenant, subscriptions):
    repository = Repository()
    with pytest.raises((tasks.UnauthorizedJob, ValueError)):
        tasks.run_scan_job(settings(), tenant, subscriptions, str(uuid4()), repository, Lease(),
                           scanner=lambda _: pytest.fail('Unauthorized scanner call'))
    assert not repository.scans


def test_database_revocation_prevents_queued_job_from_scanning():
    repository = Repository(active=[])
    with pytest.raises(tasks.UnauthorizedJob):
        tasks.run_scan_job(settings(), TENANT, [SUB], str(uuid4()), repository, Lease(),
                           scanner=lambda _: pytest.fail('Revoked subscription was scanned'))


def test_completed_job_redelivery_does_not_scan_or_notify_twice():
    repository, lease = Repository(), Lease()
    job_id = str(uuid4())
    notices = []
    result = tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, lease,
                                scanner=lambda _: [finding()], notifier=lambda scan: notices.append(scan))
    repeated = tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, Lease(),
                                  scanner=lambda _: pytest.fail('Duplicate scan'),
                                  notifier=lambda _: pytest.fail('Duplicate notification'))
    assert result == repeated
    assert len(repository.scans) == len(notices) == 1
    assert repository.jobs[job_id]['notification_status'] == 'sent'
    assert lease.released


def test_retry_keeps_scan_identity_and_commits_only_complete_snapshot():
    repository, job_id = Repository(), str(uuid4())
    repository.fail_completion = True
    with pytest.raises(RuntimeError):
        tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, Lease(), scanner=lambda _: [finding()])
    assert not repository.scans
    assert repository.jobs[job_id]['status'] == 'queued'
    repository.fail_completion = False
    result = tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, Lease(), scanner=lambda _: [finding()])
    assert result['status'] == 'completed'
    assert repository.jobs[job_id]['attempts'] == 2
    assert repository.attempted_scans[0]['scan_id'] == repository.attempted_scans[1]['scan_id']


def test_scanner_failure_has_no_completed_data_and_terminal_attempt_is_recorded():
    repository, lease, job_id = Repository(), Lease(), str(uuid4())
    def broken(_):
        raise RuntimeError('upstream failed')
    with pytest.raises(RuntimeError):
        tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, lease,
                           scanner=broken, final_attempt=True)
    assert repository.jobs[job_id]['status'] == 'failed'
    assert not repository.scans
    assert lease.released
    with pytest.raises(tasks.TerminalJob):
        tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, Lease(),
                           scanner=lambda _: pytest.fail('Terminal job reran'))


def test_hard_lost_task_cannot_exceed_durable_attempt_limit():
    repository, job_id = Repository(), str(uuid4())
    repository.jobs[job_id] = dict(status='running', attempts=4, scan_id=None)
    with pytest.raises(tasks.TerminalJob):
        tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, Lease(),
                           scanner=lambda _: pytest.fail('Exhausted job reran'))
    assert repository.jobs[job_id]['status'] == 'failed'


def test_busy_workspace_never_calls_scanner():
    repository, job_id = Repository(), str(uuid4())
    with pytest.raises(tasks.JobBusy):
        tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, Lease(False),
                           scanner=lambda _: pytest.fail('Lease was bypassed'))
    assert repository.jobs[job_id]['attempts'] == 0
    assert not repository.scans


def test_scanner_cannot_expand_subscription_scope():
    repository = Repository()
    with pytest.raises(tasks.UnauthorizedJob):
        tasks.run_scan_job(settings(), TENANT, [SUB], str(uuid4()), repository, Lease(),
                           scanner=lambda _: [finding(OTHER)])
    assert not repository.scans


def test_notification_failure_does_not_roll_back_or_rerun_scan():
    repository, job_id = Repository(), str(uuid4())
    def failed_notice(_):
        raise RuntimeError('provider unavailable')
    result = tasks.run_scan_job(settings(), TENANT, [SUB], job_id, repository, Lease(),
                                scanner=lambda _: [finding()], notifier=failed_notice)
    assert result['status'] == 'completed'
    assert repository.jobs[job_id]['notification_status'] == 'failed'
    assert len(repository.scans) == 1


def test_live_estimates_remain_unknown_and_demo_is_explicit():
    repository = Repository()
    invented = finding()
    invented['estimated_monthly_waste_usd'] = 999
    result = tasks.run_scan_job(settings(), TENANT, [SUB], str(uuid4()), repository, Lease(), scanner=lambda _: [invented])
    assert repository.scans[result['scan_id']]['total_monthly_waste_usd'] is None
    assert repository.scans[result['scan_id']]['findings'][0]['estimated_monthly_waste_usd'] is None
    demo = tasks.run_scan_job(settings('demo'), TENANT, [SUB], str(uuid4()), repository, Lease())
    assert repository.scans[demo['scan_id']]['mode'] == 'demo'
    assert repository.scans[demo['scan_id']]['total_items_found'] == 8


def test_scheduler_intersects_database_activation_with_server_allowlist(monkeypatch):
    repository = Repository(active=[SUB, OTHER])
    monkeypatch.setenv('CLOUDSAVER_SCHEDULED_SCANS', 'true')
    monkeypatch.setattr(tasks, 'dependencies', lambda: (settings(), repository, Lease()))
    queued = []
    monkeypatch.setattr(tasks.execute_subscription_scan, 'apply_async', lambda **kw: queued.append(kw))
    assert tasks.scheduled_scan_all.run() == {'scheduled': 1, 'enabled': True}
    assert queued[0]['args'] == [TENANT, [SUB]]
    assert queued[0]['task_id'] in repository.jobs


def test_starter_cannot_run_scheduled_scan():
    repository = Repository()
    repository.plan_tier = lambda _: 'STARTER'
    with pytest.raises(tasks.UnauthorizedJob):
        tasks.run_scan_job(settings(),TENANT,[SUB],str(uuid4()),repository,Lease(),
                           scanner=lambda _: pytest.fail('Starter schedule was executed'))
    assert not repository.jobs
