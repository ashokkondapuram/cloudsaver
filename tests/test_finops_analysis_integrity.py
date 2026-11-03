"""FinOps analysis catalog integrity: every family/type gets the expected rule evaluations."""
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis_rules import evaluate_inventory
from app.finops_resize_playbooks import PLAYBOOKS, resolve_playbook
from app.kubernetes_rules import DEFINITIONS as K8_DEFINITIONS, RULE_IDS as K8_RULE_IDS
from app.resource_catalog import (
    AZURE_EVIDENCE_CONTRACT_IDS,
    FAMILIES,
    RULE_DISPLAY_NAMES,
    azure_evidence_contract,
    azure_evidence_contracts,
    definitions,
    display_name,
    family,
    rule_resource_type_suffix,
)

NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
NOW -= timedelta(minutes=NOW.minute % 5)

ALLOWED_OUTCOMES = frozenset(
    {
        "condition_detected",
        "condition_not_detected",
        "insufficient_evidence",
        "not_applicable",
        "disabled_by_policy",
        "unsupported_by_collector",
        "evaluation_failed",
    }
)

RIGHTSIZING_RULE_TO_PLAYBOOK = {
    "AZURE_VM_RIGHTSIZING_UTILIZATION": "azure.vm.rightsize",
    "AZURE_ASP_UNDERUTILIZED_SKU": "azure.appservice.rightsize",
    "AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING": "aws.ec2.rightsize",
    "AWS_RDS_AURORA_RIGHTSIZING_AND_GP3": "aws.rds.rightsize",
    "GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING": "gcp.compute.rightsize",
}


def _synthetic_resource(provider: str, resource_type: str) -> dict:
    base = dict(
        resource_id=f"synthetic/{provider}/{resource_type}",
        resource_type=resource_type,
        cloud_provider=provider,
        scope_id="scope-1",
        resource_name="synthetic",
        evidence={},
        observed_at=NOW.isoformat(),
    )
    if provider == "azure":
        base["subscription_id"] = "00000000-0000-0000-0000-000000000001"
    elif provider == "aws":
        base["account_id"] = "123456789012"
    elif provider == "gcp":
        base["project_id"] = "example-project"
    elif provider == "kubernetes":
        base["cluster_id"] = "cluster-1"
        base["namespace"] = "default"
    return base


def expected_rule_ids(*, cloud_provider: str, resource_type: str) -> frozenset[str]:
    """Mirror evaluate_inventory rule selection (legacy suffix, K8 kind, multicloud family)."""
    expected: set[str] = set()
    if cloud_provider == "azure":
        suffix = resource_type.lower().rsplit("/", 1)[-1]
        for rule_id, type_suffix, *_rest in azure_evidence_contracts():
            if suffix == type_suffix:
                expected.add(rule_id)
    if cloud_provider == "kubernetes":
        kind = resource_type.split("/")[-1]
        for rule_id, kinds, *_rest in K8_DEFINITIONS:
            if kind in kinds:
                expected.add(rule_id)
    row = family({"cloud_provider": cloud_provider, "resource_type": resource_type})
    if row and row[0] != "kubernetes":
        for rule_id in row[4]:
            if rule_id not in AZURE_EVIDENCE_CONTRACT_IDS:
                expected.add(rule_id)
    return frozenset(expected)


@pytest.mark.parametrize("family_row", FAMILIES, ids=lambda row: f"{row[0]}:{row[1]}")
def test_each_catalog_family_evaluates_expected_rules_without_errors(family_row):
    provider, _name, _category, resource_types, _expected_rules = family_row
    for resource_type in resource_types:
        resource = _synthetic_resource(provider, resource_type)
        rows = evaluate_inventory([resource], observed_at=NOW.isoformat(), now=NOW)
        want = expected_rule_ids(cloud_provider=provider, resource_type=resource_type)
        assert rows or not want, f"no evaluations for {provider}/{resource_type} but expected {sorted(want)}"
        by_rule = {row["rule_id"]: row for row in rows}
        assert frozenset(by_rule) == want, (
            f"{provider}/{resource_type}: got {sorted(by_rule)} expected {sorted(want)}"
        )
        for row in rows:
            assert row["outcome"] in ALLOWED_OUTCOMES
            assert row["automatic_execution"] is False
            if row["outcome"] == "insufficient_evidence":
                assert row.get("estimated_savings") is None or row["estimated_savings"] == 0


def test_azure_evidence_contract_bounds_match_platform_identity():
    """Platform identity DEFINITIONS must stay aligned with resource_catalog contract bounds."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    platform = root / 'platform'
    if str(platform) not in sys.path:
        sys.path.insert(0, str(platform))
    from identity.analysis.contracts import DEFINITIONS

    catalog_bounds = {rid: azure_evidence_contract(rid)[3] for rid in AZURE_EVIDENCE_CONTRACT_IDS}
    identity_bounds = {row[0]: row[4] for row in DEFINITIONS}
    assert set(catalog_bounds) == set(identity_bounds)
    for rule_id in AZURE_EVIDENCE_CONTRACT_IDS:
        assert catalog_bounds[rule_id] == identity_bounds[rule_id], rule_id


def test_kubernetes_catalog_covers_all_kubernetes_rule_ids():
    catalog_rules = {rule_id for _p, _f, _c, _t, rules in FAMILIES if _p == "kubernetes" for rule_id in rules}
    assert catalog_rules == set(K8_RULE_IDS)


def test_legacy_azure_rules_still_map_to_vm_disk_and_ip_types():
    legacy_suffixes = {rule_resource_type_suffix(rid) for rid in AZURE_EVIDENCE_CONTRACT_IDS}
    assert legacy_suffixes >= {"disks", "virtualmachines", "publicipaddresses", "serverfarms"}


@pytest.mark.parametrize(
    "rule_id,playbook_key",
    list(RIGHTSIZING_RULE_TO_PLAYBOOK.items()),
    ids=lambda x: x[0],
)
def test_rightsizing_rules_have_resize_playbooks(rule_id, playbook_key):
    assert playbook_key in PLAYBOOKS
    book = PLAYBOOKS[playbook_key]
    provider = book["cloud_provider"]
    resource_type = next(
        t for _p, _f, _c, types, rules in FAMILIES if rule_id in rules for t in types
    )
    resolved = resolve_playbook(cloud_provider=provider, resource_type=resource_type)
    assert resolved["finops_action"] == playbook_key


def test_platform_identity_families_match_app_catalog():
    from pathlib import Path

    ns: dict = {}
    exec(Path("platform/identity/analysis/multicloud.py").read_text(), ns)
    assert ns["FAMILIES"] == FAMILIES


def test_autopilot_playbooks_align_with_finops_rule_routing():
    from app.agent_workflow_routing import FINOPS_RULE_TO_ACTION

    autopilot_actions = frozenset(FINOPS_RULE_TO_ACTION.values())
    assert autopilot_actions <= frozenset(PLAYBOOKS)
    assert "azure.disk.rightsize" in PLAYBOOKS
    assert "azure.disk.rightsize" not in autopilot_actions


def test_family_lookup_matches_catalog_rows():
    for provider, _name, _category, resource_types, rules in FAMILIES:
        for resource_type in resource_types:
            row = family(_synthetic_resource(provider, resource_type))
            assert row is not None
            assert row[4] == rules


def test_definitions_cover_every_catalog_rule_once():
    published = {row[0] for row in definitions()}
    catalog_rules = {rule_id for _p, _f, _c, _t, rules in FAMILIES for rule_id in rules}
    assert published == catalog_rules


def test_every_catalog_rule_has_human_display_name():
    for rule_id in {rid for *_, rules in FAMILIES for rid in rules}:
        name = RULE_DISPLAY_NAMES[rule_id]
        assert name != rule_id
        assert '_' not in name or name.startswith('RDS /')
    for row in definitions():
        assert row[4] == RULE_DISPLAY_NAMES[row[0]]


def test_every_catalog_rule_has_action_class():
    from app.resource_catalog import definitions
    from app.rule_match_strategy import ACTION_CLASS_BY_RULE

    catalog = {row[0] for row in definitions()}
    missing = catalog - set(ACTION_CLASS_BY_RULE)
    assert not missing, f"Add ActionClass for: {sorted(missing)}"


def test_analysis_rules_master_doc_covers_catalog():
    from pathlib import Path
    import re

    doc = (Path(__file__).resolve().parents[1] / "docs" / "ANALYSIS_RULES_MASTER.md").read_text()
    catalog = {row[0] for row in definitions()}
    found = set(re.findall(r"`([A-Z0-9_]+)`", doc))
    missing = catalog - found
    assert not missing, f"ANALYSIS_RULES_MASTER.md missing rule ids: {sorted(missing)}"
