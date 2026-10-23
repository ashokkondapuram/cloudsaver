"""Plan entitlements: the platform plan block, the TIER_LIMITS fallback and enforcement messages."""
import copy
import logging

import pytest
from fastapi import HTTPException

import app.entitlements as entitlements
from app.entitlements import (billing_summary, enforce_automated_alerts, enforce_keyvault_access, enforce_providers,
                              enforce_resource_quota, enforce_scan_frequency, enforce_subscription_quota,
                              enforce_terraform_export, entitlements_for, fallback_entitlements, normalize_plan)
from tests.identity_fake import TID, fixture

CONTACT = 'Contact your account manager.'


def plan(**changes):
    block = copy.deepcopy(fixture('verify_valid')['plan'])
    limits = changes.pop('entitlements', {})
    block.update(changes)
    block['entitlements'].update(limits)
    return block


def workspace(**changes):
    return dict(tenant_id=TID, name='Contoso', plan_tier='STARTER', subscription_ids=['a', 'b'],
                aws_accounts=[{'account_id': '123456789012'}], gcp_projects=[], kubernetes_clusters=[]) | changes


def denied(call, *args):
    with pytest.raises(HTTPException) as error:
        call(*args)
    return error.value.status_code, error.value.detail


def test_platform_plan_block_wins_over_plan_tier():
    result = entitlements_for(workspace(plan=plan()))
    assert result.source == 'platform' and result.tier == 'GROWTH' and result.plan_name == 'Growth'
    assert result.billing_state == 'grace' and result.manage_billing_url == 'https://billing.example.com/acme'
    assert result.max_subscriptions == 10 and result.entitlements_version == 7


def test_fallback_uses_tier_limits_and_logs_once(monkeypatch, caplog):
    monkeypatch.setattr(entitlements, '_warned', set())
    with caplog.at_level(logging.WARNING, logger='cloudsaver.entitlements'):
        first = entitlements_for(workspace(plan_tier='ENTERPRISE'))
        entitlements_for(workspace(plan_tier='ENTERPRISE'))
    assert first.source == 'fallback' and first.billing_state == 'none' and first.can_use_keyvault
    assert [r.getMessage() for r in caplog.records] == [f'entitlements_fallback tenant_id={TID} plan=ENTERPRISE']


def test_tier_limits_are_unchanged():
    starter, growth, enterprise = (fallback_entitlements(t) for t in ('STARTER', 'GROWTH', 'ENTERPRISE'))
    assert (starter.max_subscriptions, starter.max_resources_per_scan, starter.retention_days) == (2, 250, 7)
    assert not starter.can_export_terraform and not starter.can_use_keyvault and starter.allowed_scan_frequencies == ['manual']
    assert growth.can_export_terraform and not growth.can_use_keyvault and growth.allowed_scan_frequencies == ['manual', 'daily']
    assert enterprise.can_use_keyvault and enterprise.allowed_scan_frequencies == ['manual', 'daily', 'hourly']


def test_custom_plan_codes_fall_back_to_starter_limits_under_their_own_code():
    custom = fallback_entitlements('PARTNER_2026')
    assert custom.tier == 'PARTNER_2026' and custom.plan_name == 'Partner_2026' and custom.max_subscriptions == 2
    assert fallback_entitlements('not a code').tier == 'STARTER'


def test_normalize_plan_canonicalizes_and_rejects_malformed_blocks():
    normalized = normalize_plan(plan(code='growth', current_period_end='2026-11-30T00:00:00+00:00',
                                     entitlements={'allowed_scan_frequencies': ['daily']}))
    assert normalized['code'] == 'GROWTH' and normalized['current_period_end'] == '2026-11-30T00:00:00Z'
    assert normalized['entitlements']['allowed_scan_frequencies'] == ['manual', 'daily']
    assert normalize_plan(None) is None
    for bad in (plan(billing_state='overdue'), plan(code='1BAD'), plan(entitlements={'max_subscriptions': -1}),
                plan(entitlements={'can_use_keyvault': 'yes'}), plan(entitlements={'allowed_providers': ['oracle']}),
                plan(entitlements_version=True), plan(current_period_end='soon'), 'GROWTH'):
        with pytest.raises(ValueError):
            normalize_plan(bad)


@pytest.mark.parametrize('url', ['http://billing.example.com', 'https://user:pass@billing.example.com',
                                 'https://billing.example.com/a b', 'javascript:alert(1)', 'https://' + 'a' * 2050])
def test_unsafe_manage_billing_urls_are_dropped(url):
    assert normalize_plan(plan(manage_billing_url=url))['manage_billing_url'] is None


def test_malformed_plan_falls_back_instead_of_failing():
    assert entitlements_for(workspace(plan=plan(billing_state='overdue'), plan_tier='GROWTH')).source == 'fallback'


def test_quota_messages_name_the_plan_and_the_account_manager():
    growth = workspace(plan=plan(entitlements={'max_subscriptions': 3}))
    enforce_subscription_quota(growth, 2, 1)
    assert denied(enforce_subscription_quota, growth, 3, 1) == (
        402, 'Your Growth plan allows up to 3 cloud scopes. Contact your account manager to change your plan.')
    assert denied(enforce_subscription_quota, 'STARTER', 2, 1)[0] == 402
    status, detail = denied(enforce_resource_quota, growth, 2501)
    assert status == 402 and '2,500 resources' in detail and 'Growth plan' in detail
    enforce_resource_quota(growth, 2500)


def test_feature_gates_use_the_new_texts():
    starter = workspace(plan=plan(code='STARTER', name='Starter', entitlements={
        'can_export_terraform': False, 'can_dispatch_automated_alerts': False, 'allowed_scan_frequencies': ['manual'],
        'allowed_providers': ['azure']}))
    assert denied(enforce_terraform_export, starter) == (
        403, 'Terraform review is available on plans that include it. Contact your account manager.')
    assert denied(enforce_keyvault_access, starter) == (403, "Key Vault access isn't included in your plan. " + CONTACT)
    assert denied(enforce_scan_frequency, starter, 'daily') == (402, "Daily scans aren't included in your plan. " + CONTACT)
    assert denied(enforce_automated_alerts, starter) == (402, "Automated alerts aren't included in your plan. " + CONTACT)
    assert denied(enforce_providers, starter, ['azure', 'aws']) == (403, "AWS isn't included in your plan. " + CONTACT)
    enforce_scan_frequency(starter, 'manual')
    enforce_providers(starter, ['azure'])
    enforce_terraform_export('GROWTH')
    enforce_keyvault_access('ENTERPRISE')


def test_billing_summary_has_exactly_the_dashboard_fields():
    summary = billing_summary(workspace(plan=plan()))
    assert list(summary) == ['tenant_id', 'tier', 'plan_name', 'billing_state', 'current_period_end', 'grace_ends_at',
                             'subscription_plan_name', 'manage_billing_url', 'max_subscriptions', 'current_subscriptions',
                             'max_resources_per_scan', 'allowed_scan_frequencies', 'allowed_providers',
                             'can_export_terraform', 'can_use_keyvault', 'can_dispatch_automated_alerts', 'retention_days',
                             'entitlements_source', 'settings_version', 'plan_change_allowed']
    assert summary['current_subscriptions'] == 3 and summary['entitlements_source'] == 'platform'
    narrowed = billing_summary(workspace(plan=plan(), subscription_ids=[]), workspace())
    assert narrowed['current_subscriptions'] == 3


def test_operations_follow_the_plan_block(monkeypatch):
    from app.operations import alerts_enabled, effective_frequency, scheduled_interval
    monkeypatch.setenv('CLOUDSAVER_SCHEDULED_SCANS', 'true')
    monkeypatch.setenv('CLOUDSAVER_AUTOMATED_ALERTS', 'true')
    hourly = workspace(plan=plan(entitlements={'allowed_scan_frequencies': ['manual', 'daily', 'hourly']}),
                       schedule={'frequency': 'hourly'})
    assert effective_frequency(hourly) == 'hourly' and scheduled_interval(None, hourly) == 3600
    assert effective_frequency(dict(hourly, plan=plan())) == 'daily'
    assert scheduled_interval(None, hourly, 'STARTER') is None
    assert alerts_enabled(None, hourly) is True
    assert alerts_enabled(None, dict(hourly, plan=plan(entitlements={'can_dispatch_automated_alerts': False}))) is False
