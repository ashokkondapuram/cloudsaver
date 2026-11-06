"""Catalog + declarative JSON + built-in platform rules."""

import json
from pathlib import Path

from app.analysis_service.context import ConfigMetadata, UnifiedResourceContext
from app.analysis_service.declarative_rules import clear_declarative_rules_cache_for_tests, extend_resource_catalog_definitions
from app.analysis_service.service import AnalysisService
from app.resource_catalog import definitions, rules_catalog_items, RULE_DISPLAY_NAMES


def test_platform_rules_in_catalog():
    ids = {row[0] for row in definitions()}
    assert 'PLATFORM_DEFAULT_TAGS' in ids
    assert 'PLATFORM_PROD_ENCRYPTION_EXPECTATION' in ids
    assert 'PLATFORM_DEFAULT_TAGS' in RULE_DISPLAY_NAMES
    items = {r['id']: r for r in rules_catalog_items()}
    assert items['PLATFORM_DEFAULT_TAGS']['provider'] == 'platform'


def test_declarative_rules_extend_catalog(tmp_path, monkeypatch):
    clear_declarative_rules_cache_for_tests()
    path = tmp_path / 'rules.json'
    path.write_text(
        json.dumps(
            {
                'version': 1,
                'rules': [
                    {
                        'id': 'PLATFORM_JSON_UNIT_TEST',
                        'display_name': 'Unit test declarative rule',
                        'pillar': 'COST_OPTIMIZATION',
                        'severity': 'LOW',
                        'remediation_action': 'Fix tags',
                        'when': {'all': [{'tag_missing': 'cost_center'}]},
                    }
                ],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setenv('CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES', str(path))
    rows = extend_resource_catalog_definitions()
    assert any(r[0] == 'PLATFORM_JSON_UNIT_TEST' for r in rows)
    assert RULE_DISPLAY_NAMES['PLATFORM_JSON_UNIT_TEST'] == 'Unit test declarative rule'


def test_builtin_platform_tag_rule(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES', raising=False)
    clear_declarative_rules_cache_for_tests()
    ctx = UnifiedResourceContext(
        provider='aws',
        resource_id='arn:aws:ec2:us-east-1:1:instance/i-1',
        resource_type='aws:ec2:instance',
        tags={'environment': 'staging'},
    )
    findings = [f for f in AnalysisService().analyze_resource(ctx).findings if f.rule_id == 'PLATFORM_DEFAULT_TAGS']
    assert findings and findings[0].severity.value == 'MEDIUM'


def test_prod_encryption_platform_rule(monkeypatch):
    monkeypatch.delenv('CLOUDSAVER_ANALYSIS_DECLARATIVE_RULES', raising=False)
    clear_declarative_rules_cache_for_tests()
    ctx = UnifiedResourceContext(
        provider='azure',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa',
        resource_type='microsoft.storage/storageaccounts',
        tags={'env': 'prod'},
        config=ConfigMetadata(encrypted_at_rest=False),
    )
    findings = [f for f in AnalysisService().analyze_resource(ctx).findings if f.rule_id == 'PLATFORM_PROD_ENCRYPTION_EXPECTATION']
    assert findings and findings[0].pillar.value == 'SECURITY'
