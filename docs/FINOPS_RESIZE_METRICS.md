# FinOps resize metrics API

Deterministic **resize review metrics** from a **completed live scan**. This endpoint does not call cloud APIs; it re-validates saved telemetry against the same contracts used during analysis.

## Endpoint

```http
GET /api/v1/finops/autopilot/resize-metrics?scan_id={uuid}&eligible_only=false&cloud_provider=azure
```

**Auth:** workspace role (same as other FinOps autopilot routes). Via gateway: forwarded to the scanner service.

**Query parameters**

| Parameter | Description |
| --- | --- |
| `scan_id` | Completed scan UUID (required) |
| `eligible_only` | When `true`, return only rows with `resize_eligible: true` |
| `cloud_provider` | Optional filter: `azure`, `aws`, or `gcp` |

## Response (schema version 1)

| Field | Meaning |
| --- | --- |
| `items[].resource_id` | Provider resource identifier |
| `items[].finops_action` | Resize playbook key (e.g. `azure.vm.rightsize`) |
| `items[].rule_id` / `rule_name` | Analysis rule that gates rightsizing |
| `items[].current_size` | `{ field, value }` from scan evidence (e.g. `vm_size`) |
| `items[].recommended_size` | Candidate from evidence when present; otherwise `null` |
| `items[].resize_eligible` | `true` only when rule outcome, telemetry, SLO, and safety gates align |
| `items[].eligibility_reasons` | Machine-readable blockers when not eligible |
| `items[].metrics[]` | Per-series contract evaluation (coverage, P95/P99/MAX, gap reason) |
| `items[].slo` | SLO gate snapshot for compute rightsizing playbooks |
| `items[].evaluation` | Saved rule outcome (`condition_detected`, etc.) |

## Telemetry contract (robust data rules)

Each metric series in `items[].metrics` is evaluated with `TimeSeriesEvidenceContract`:

- **30-day** window, **5-minute** buckets  
- **≥ 95%** sample coverage  
- No gap **> 60 minutes**  
- Resource age **≥ 30 days** when `created_at` is present  
- **No zero-filling** — missing points stay insufficient  

Rightsizing rows additionally require:

- Rule **`condition_detected`** for the playbook’s primary rule (see [RESOURCE_ANALYSIS_RULES.md](RESOURCE_ANALYSIS_RULES.md))  
- **SLO gate pass** (`burn_rate ≤ 1`, correlation ≤ 0.6, no recent OOM/throttling signals) for VM/EC2/GCE/RDS playbooks  
- No **`safety_blocks`** or **`destructive_actions_blocked`** on the evaluation  

## Playbooks covered

| `finops_action` | Primary rule | Key metrics |
| --- | --- | --- |
| `azure.vm.rightsize` | `AZURE_VM_RIGHTSIZING_UTILIZATION` | CPU/memory P95, disk IOPS max, network max |
| `azure.appservice.rightsize` | `AZURE_ASP_UNDERUTILIZED_SKU` | CPU/memory P95 |
| `azure.disk.rightsize` | `AZURE_DISK_PROVISIONED_PERFORMANCE` | IOPS/throughput P99 |
| `aws.ec2.rightsize` | `AWS_EC2_GRAVITON_AND_SLO_RIGHTSIZING` | CPU/memory P95 + SLO |
| `aws.rds.rightsize` | `AWS_RDS_AURORA_RIGHTSIZING_AND_GP3` | CPU/memory P95 + SLO |
| `gcp.compute.rightsize` | `GCP_GCE_AXION_AND_CUSTOM_RIGHTSIZING` | CPU/memory P95 + SLO |

## Example

```json
{
  "schema_version": 1,
  "scan_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "eligible_count": 1,
  "items": [
    {
      "resource_id": "/subscriptions/.../virtualMachines/app",
      "finops_action": "azure.vm.rightsize",
      "rule_name": "Evidence-based VM rightsizing review",
      "current_size": {"field": "vm_size", "value": "Standard_D8s_v5"},
      "recommended_size": "Standard_D4s_v5",
      "resize_eligible": true,
      "eligibility_reasons": [],
      "metrics": [
        {
          "metric": "cpu_percent",
          "aggregation": "P95",
          "sufficient": true,
          "coverage_ratio": 0.9999,
          "observed_value": 4.0,
          "contract": {"window_days": 30, "min_coverage_ratio": 0.95}
        }
      ],
      "slo": {"status": "pass", "burn_rate": 0.3}
    }
  ]
}
```

## Related

- `POST /api/v1/finops/autopilot/resize` — build/execute agent plan after review  
- [FINOPS_ANALYSIS_VERIFICATION.md](FINOPS_ANALYSIS_VERIFICATION.md)  
- [RESOURCE_ANALYSIS_RULES.md](RESOURCE_ANALYSIS_RULES.md)  
