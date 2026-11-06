"""Wiz CSPM issue enrichment and security finding."""

import pytest

from app.analysis_service.context import UnifiedResourceContext
from app.analysis_service.evaluators import security as sec_eval
from app.collectors.wiz_security import enabled, enrich_inventory_wiz_signals


def test_enrich_inventory_wiz_signals_matches_azure_arm_id(monkeypatch):
    monkeypatch.setenv('CLOUDSAVER_WIZ_ENABLED', 'true')

    vm_id = '/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1'

    def fake_fetch():
        return [
            {
                'source': 'wiz',
                'issue_id': 'wiz-issue-1',
                'severity': 'HIGH',
                'status': 'OPEN',
                'rule_id': 'rule-a',
                'rule_name': 'Test rule',
                'external_id': vm_id,
                'cloud_platform': 'Azure',
            }
        ]

    monkeypatch.setattr('app.collectors.wiz_security.fetch_wiz_issues', fake_fetch)

    inventory = [
        {
            'cloud_provider': 'azure',
            'resource_id': vm_id,
            'evidence': {},
        }
    ]
    enrich_inventory_wiz_signals(inventory, settings=None)
    w = inventory[0]['evidence']['wiz_issues']
    assert len(w) == 1
    assert w[0]['issue_id'] == 'wiz-issue-1'


def test_wiz_security_finding_emitted_from_context():
    ctx = UnifiedResourceContext(
        provider='azure',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa',
        resource_type='microsoft.storage/storageaccounts',
        region='eastus',
        wiz_issues=[
            {'issue_id': '1', 'severity': 'CRITICAL', 'status': 'OPEN', 'rule_name': 'r1'},
            {'issue_id': '2', 'severity': 'LOW', 'status': 'OPEN', 'rule_name': 'r2'},
        ],
    )
    findings = sec_eval.evaluate(ctx)
    wiz_rows = [f for f in findings if f.rule_id == 'WIZ_SECURITY_POSTURE']
    assert len(wiz_rows) == 1
    assert wiz_rows[0].severity.value == 'CRITICAL'
    assert wiz_rows[0].evidence['open_issue_count'] == 2
