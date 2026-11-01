import pytest

from app.ai_foundry_client import AzureAIFoundryClient
from app.ai_processor_guard import scrub_secrets
from app.ai_workload_optimizer import ptu_break_even_tokens_per_min
from app.autopilot_commitments import commitment_ladder
from app.collectors_ebpf_flow import normalize_flow_record, topology_routing_manifest
from app.drift.live_readers import reader_for_provider
from app.finops_saas_focus_connectors import normalize_focus_record
from app.finops_spot_arbitrage import arbitrage_node_pool_capacity
from app.gitops_pre_merge_firewall import score_pull_request
from app.governance_ephemeral_reaper import lease_expired, stage_teardown_plan
from app.governance_merkle_audit import MerkleAuditChain, chain_hash
from app.k8s_karpenter_sync import draft_aks_nap_node_pool, draft_node_pool
from app.scanner_ai_gpu import mig_partition_advisory, validate_dcgm_sample
from app.scanner_greenops import compute_carbon_footprint


def test_mig_partition_advisory_respects_slo():
    result = mig_partition_advisory(peak_vram_gb="32", slo_latency_p99_ms="120")
    assert result["mig_partition_recommended"] is True


def test_ptu_break_even_math():
    result = ptu_break_even_tokens_per_min(
        payg_usd_per_1k_tokens="0.01",
        ptu_usd_hr="100",
        ptu_tokens_per_min_capacity="10000",
    )
    assert "ptu_favorable" in result


def test_aks_nap_draft():
    manifest = draft_aks_nap_node_pool("batch", ["Standard_D4s_v5"], 10)
    assert manifest["kind"] == "AKSNodeClass"


def test_saas_focus_normalization():
    row = normalize_focus_record(
        "snowflake",
        {"BilledCost": "12.5", "EffectiveCost": "10", "ChargePeriodStart": "2026-10-01", "ChargePeriodEnd": "2026-10-31"},
    )
    assert row["provider_name"] == "snowflake"


def test_ebpf_flow_cost_attribution():
    row = normalize_flow_record(
        dict(
            cluster_id="prod",
            traffic_class="cross_az",
            bytes_transferred=1024**3,
            usd_per_gb="0.01",
            window_start="2026-10-01T00:00:00Z",
            window_end="2026-10-01T01:00:00Z",
        )
    )
    assert float(row["attributed_cost_usd"]) == pytest.approx(0.01, rel=1e-6)


def test_pre_merge_scorecard():
    score = score_pull_request(plan_json={"monthly_delta": "125.00"}, files_changed=["main.tf"])
    assert score["terraform_files"] == 1


def test_greenops_carbon():
    carbon = compute_carbon_footprint(energy_kwh="100", grid_intensity_gco2_kwh="50")
    assert float(carbon["scope2_gco2e"]) == 5000.0


def test_spot_arbitrage_prefers_commitment():
    result = arbitrage_node_pool_capacity(
        unused_commitment_usd_hr="5", spot_interruption_score="0.1", on_demand_usd_hr="1"
    )
    assert result["prefer_prepaid_commitment"] is True


def test_ephemeral_lease_reaper_stages_plan():
    tags = {"cloudsaver:lease-expires-at": "2020-01-01T00:00:00+00:00"}
    assert lease_expired(tags) is True
    plan = stage_teardown_plan("/subscriptions/x/providers/Microsoft.Compute/virtualMachines/vm", tags)
    assert plan["automatic_execution"] is False


def test_merkle_chain_links_hashes():
    first = chain_hash("0" * 64, "abc", tenant_id="t", category="permit", actor="a", recorded_at="2026-01-01T00:00:00Z")
    second = chain_hash(first, "def", tenant_id="t", category="drift", actor="a", recorded_at="2026-01-01T00:01:00Z")
    assert first != second


def test_processor_guard_scrubs_aws_key():
    assert "[REDACTED]" in scrub_secrets("key AKIAIOSFODNN7EXAMPLE")


def test_ai_foundry_requires_purpose():
    client = AzureAIFoundryClient(enabled=True)
    with pytest.raises(PermissionError):
        client.complete({"ai_enabled": True, "ai_purposes": ["investigation"]}, purpose="drift_classification", payload={})


def test_live_reader_factory():
    assert reader_for_provider("azure")({})["source"] == "azure_live_stub"


def test_topology_manifest():
    assert topology_routing_manifest()["spec"]["trafficDistribution"] == "PreferClose"


def test_commitment_ladder_quarters():
    steps = commitment_ladder("10.0000", "2.0000", "1.0000")
    assert len(steps) == 3 and steps[0]["quarter"] == 1


def test_validate_dcgm_rejects_none_sample():
    with pytest.raises(ValueError, match="zero-filled"):
        validate_dcgm_sample(None)


def test_draft_node_pool_still_works():
    assert draft_node_pool("pool", ["m6i.large"], "10")["kind"] == "NodePool"


def test_gitops_delivery_kwargs_none_when_publish_disabled(monkeypatch):
    from app.gitops_remediation_loaders import gitops_delivery_kwargs

    monkeypatch.delenv("CLOUDSAVER_GITOPS_PUBLISH", raising=False)
    monkeypatch.setenv("CLOUDSAVER_GITOPS_TARGETS", "[]")
    tenant_id = "00000000-0000-4000-8000-000000000000"
    assert gitops_delivery_kwargs(object(), tenant_id) is None

