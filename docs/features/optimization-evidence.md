# Optimization evidence

The optimization evidence page shows the planning inputs CloudSaver can derive automatically from the scan you selected, together with the imported billing attached to that scan. It reports four input groups: verified dependency edges (topology), SLO burn-rate signals, network traffic observations, and a commitment baseline. Each group shows either the saved observations or an explicit "insufficient evidence" status. The page does not generate synthetic savings, does not authorize commitment purchases, and does not execute changes.

Last reviewed: Oct 25, 2026.

## Where to find it

- **Route:** `/optimization`, rendered by `OptimizationWorkspace` in [web-dashboard/components/V150Views.tsx](../../web-dashboard/components/V150Views.tsx) through [web-dashboard/app/optimization/page.tsx](../../web-dashboard/app/optimization/page.tsx). This page does not go through [ConsolePage.tsx](../../web-dashboard/components/ConsolePage.tsx).
- **Navigation label:** **Optimization evidence**, the first item in the **Model & attribute** sidebar group ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)).
- **Who can see it:** Any signed-in workspace role (`Viewer`, `BillingAdmin` or `TenantAdmin`).

## What you can do

- **Load planning inputs for a scan.** Select a completed live scan in the workspace. The page loads its planning inputs automatically. With no scan selected, it asks you to choose one.
- **Review each engine.** The page shows one panel per input group: topology, SLO, network and commitment. Each panel shows:
  - A status badge, such as `observed_edges`, `observed_signals`, `modeled_saved_hourly_evidence` or `insufficient_evidence`.
  - How many saved observations are available, or a note that more verified observations are needed.
  - The engine's warning, when it has one.
- **Inspect raw evidence.** Expand **Inspect source evidence** in any panel to see the exact JSON the API returned for that engine.
- **Read the overall warning.** The notice at the top restates that incomplete histories, graph coverage and rates remain unknown, and that no synthetic savings are generated.

## How it works

1. **Request.** The page calls `GET /api/v1/optimization/scans/{scan_id}/auto-scenarios`. The gateway ([services/gateway.py](../../services/gateway.py)) forwards the call to the scanner service.
2. **Ownership check.** `automatic_scenarios` in [app/v150_analysis.py](../../app/v150_analysis.py) loads the scan for your workspace. It returns `404` if the scan is not yours and `409` if the scan is not `completed` or is `legacy_synthetic`. It then calls `FocusRepository.attach` ([app/focus.py](../../app/focus.py)) to merge imported billing into each resource's evidence.
3. **Input extraction.** For every inventory row and finding in the scan:
   - **Topology:** `evidence.verified_dependencies` edges whose source and target are both visible in the scan. Each item is reported with `inventory_complete: false`, and the engine reports `blast_radius_verified: false`.
   - **SLO:** numeric `evidence.slo_burn_rate` values. The engine reports `change_authorized: false`.
   - **Network:** any of `cross_az_traffic_gb`, `network_egress_gb` and `nat_bytes` found in evidence. The engine reports `savings_usd: null`.
   - **Commitment:** the result of `planning_summary()` in [app/resource_assessment.py](../../app/resource_assessment.py).
   Each list is capped at 1,000 items.
4. **Commitment baseline.** `planning_summary()` runs only when the scan has `commitment_evidence` with `source_verified: true`. It then:
   1. Validates `usage_series` and `cleanup_series` with `hourly_profile()` in [app/nextgen_engines.py](../../app/nextgen_engines.py). Each must be `USD/hour`, cover an aligned 30-day window, and contain exactly 720 hourly points. Missing hours are never filled with zero.
   2. Requires identical windows and `commitment_coverage_verified: true`, and rejects any hour where cleanup exceeds usage.
   3. Subtracts cleanup from usage hour by hour, then takes the nearest-rank P10 with `hourly_p10()` in [app/commitment_arbitrage.py](../../app/commitment_arbitrage.py).
   4. Calls `calculate_clean_commitment_baseline()` with that P10, zero open waste, and `existing_commitments_hr`. The result is `clean_steady_state_hr` and `recommended_new_commitment_hr = max(0, clean − existing)`.

   For example, if the cleaned P10 is $12.50 per hour and existing commitments cover $10.00 per hour, the modeled additional commitment is $2.50 per hour. Amounts are exact decimal strings with at most four fractional digits. Floats, booleans and scientific notation are rejected.
5. **Scoped keys.** If the scan was filtered for a provider-limited or scope-limited key (`provider_filtered` or `scope_filtered`), commitment evidence is dropped and the commitment engine reports `insufficient_evidence`.

### Related modules

These modules contain planning math. Only part of it is reachable from this page.

| Module | What it provides | Where it is used |
| --- | --- | --- |
| [app/commitment_arbitrage.py](../../app/commitment_arbitrage.py) | `parse_strict_monetary_decimal`, `calculate_clean_commitment_baseline`, `hourly_p10`, `commitment_firewall` | Baseline math for the commitment engine. `commitment_firewall` also flags commitment and provisioned-capacity changes in Terraform plan guardrails ([app/plan_policy.py](../../app/plan_policy.py)). |
| [app/nextgen_engines.py](../../app/nextgen_engines.py) | `hourly_profile`, `compute_clean_before_commit_plan`, `simulate_topology_blast_radius` | `hourly_profile` validates the commitment engine series. The other two are covered by tests but not exposed by any API route. |
| [app/causal_topology_simulator.py](../../app/causal_topology_simulator.py) | `evaluate_slo_bounded_rightsizing`, `simulate_cascading_topology_savings`, `analyze_cross_az_and_nat_hairpin_waste`, `analyze_ephemeral_batch_waste` | `evaluate_slo_bounded_rightsizing` gates Kubernetes patch previews ([app/kubernetes_api.py](../../app/kubernetes_api.py)) and multi-cloud rule materialization ([app/multicloud_rules.py](../../app/multicloud_rules.py)). The other functions are covered by tests but not exposed by any API route. |
| [app/pricing.py](../../app/pricing.py) | `attribute_finding_cost`, `regional_attribution`, `opportunity_totals` | Runs at scan time. It attaches retail list-price estimates (`cost_attribution`, `estimated_monthly_waste_usd`) to findings and rolls up opportunity totals by taking the largest alternative per group. This page does not recompute prices. |

## API reference

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| GET | `/api/v1/optimization/scans/{scan_id}/auto-scenarios` | Return the topology, SLO, network and commitment planning inputs for a completed live scan. The response always includes `automatic_execution: false` and `purchase_authorized: false`. | Any workspace role. Route class `scoped_read`. |

The router is defined in [app/v150_analysis.py](../../app/v150_analysis.py) and proxied by [services/gateway.py](../../services/gateway.py). The same router also serves `GET /api/v1/services/{service}`, which the Services page uses.

## Data and evidence

**What's stored**

This page writes nothing. It reads the saved scan (inventory, findings and evidence) and the imported FOCUS charges in the enterprise evidence store.

**Provenance**

- Topology, SLO and network inputs come only from fields already in saved evidence.
- The commitment baseline comes only from `commitment_evidence` that is marked `source_verified`.
- Retail estimates in findings come from exact Azure retail meters or from the operator-reviewed AWS and GCP catalog in `CLOUDSAVER_REGIONAL_PRICE_CATALOG`. They are labeled as retail estimates, not verified savings.

**What is NOT proven**

- `blast_radius_verified`, `change_authorized` and `purchase_authorized` are always false. `savings_usd` and `verified_realized_savings_usd` are always null.
- A monthly total cannot establish a steady hourly commitment floor. Commitment math requires complete hourly evidence.
- Future demand, commitment utilization, contract eligibility and amortization basis are not verified.
- No collector in this repository currently writes `commitment_evidence`, `verified_dependencies`, `slo_burn_rate` or the network traffic fields. In a typical scan, all four engines therefore report `insufficient_evidence` until those fields are supplied.

## Permissions

Any authenticated workspace role can read this page. Provider-limited keys only see scans whose providers they are allowed to read (`scoped_read`), and commitment evidence is withheld for filtered scans. The page has no write actions.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_REGIONAL_PRICE_CATALOG` | JSON list (up to 1,000) of operator-reviewed USD regional meters for AWS and GCP retail estimates. Each entry needs `source`, `reviewed_at` and `expires_at`, and a review lasts at most 90 days. | `[]` |

The commitment and topology engines have no feature flags. Their output depends only on the evidence in the scan.

## Guardrails and limitations

- No synthetic savings, purchases or infrastructure changes. Every response states this explicitly.
- Each input list is capped at 1,000 items.
- Commitment math accepts only USD/hour series over an aligned 30-day window with 720 points. Other units, gaps or duplicate hours make the engine report insufficient evidence.
- Planning functions that are not routed through an API (`compute_clean_before_commit_plan`, `simulate_topology_blast_radius`, `simulate_cascading_topology_savings`, the network and batch analyzers) are not available from the dashboard.
- Results reflect the selected scan only. Select a newer scan to refresh the inputs.

## Tests

- [tests/test_v150_workflows.py](../../tests/test_v150_workflows.py): `test_service_and_optimization_views_use_owned_observations` checks that the route reports `automatic_execution: false`, that topology reports insufficient evidence without edges, and that unknown scans return `404`.
- [tests/test_high_impact_improvements.py](../../tests/test_high_impact_improvements.py): strict money parsing, the clean commitment floor, cascading topology math, SLO gates, network and batch analyzers.
- [tests/test_v140.py](../../tests/test_v140.py): `compute_clean_before_commit_plan` and `simulate_topology_blast_radius`.
- [tests/test_pricing.py](../../tests/test_pricing.py) and [tests/test_opportunity_groups.py](../../tests/test_opportunity_groups.py): retail meter attribution and opportunity rollups.
- [web-dashboard/e2e/v150.spec.ts](../../web-dashboard/e2e/v150.spec.ts): the optimization destination shows observed data and honest evidence gaps.
- [web-dashboard/e2e/opportunity-totals.spec.ts](../../web-dashboard/e2e/opportunity-totals.spec.ts): connected alternatives contribute their maximum, and unknown totals stay separate.

## Related docs

- [Next-gen implementation](../NEXT_GEN_IMPLEMENTATION.md)
- [Next-gen differentiators](../NEXT_GEN_CLOUDSAVER_DIFFERENTIATORS_README.md)
- [Lean core implementation](../LEAN_CORE_IMPLEMENTATION.md) (regional price catalog contract)
- [v1.5.0 implementation](../V1_5_0_IMPLEMENTATION.md)
- [Kubernetes and containers](kubernetes.md)
- [Cost allocation and billing](cost-allocation-and-billing.md)
