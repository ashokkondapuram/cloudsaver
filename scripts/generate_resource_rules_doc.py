#!/usr/bin/env python3
"""Regenerate docs/RESOURCE_ANALYSIS_RULES.md from the live resource catalog."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis_rules import RULES, evaluate_inventory  # noqa: E402
from app.resource_catalog import FAMILIES, RULE_DISPLAY_NAMES, display_name  # noqa: E402

NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
NOW -= timedelta(minutes=NOW.minute % 5)


def synthetic(provider: str, resource_type: str) -> dict:
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


def main() -> None:
    lines = [
        "# Analysis rules by resource type",
        "",
        "This document is generated from the v1.4 resource catalog (`app/resource_catalog.py`). ",
        "For each canonical **resource type**, it lists every **rule_id** the scan engine evaluates on a completed observation, plus the operator-facing **display name**.",
        "",
        "Regenerate after catalog changes:",
        "",
        "```bash",
        "PYTHONPATH=. python3 scripts/generate_resource_rules_doc.py",
        "```",
        "",
        "Stable policy keys remain the `rule_id` values; UI and evaluations use the **display name** from `RULE_DISPLAY_NAMES`.",
        "",
        "**Evaluation wiring:**",
        "- **Azure** legacy rules match the ARM type suffix (e.g. `.../disks` → disk rules).",
        "- **Kubernetes** rules match workload **kind** (e.g. `Container`, `Deployment`).",
        "- **AWS / GCP / Azure (catalog)** rules come from the resource **family** row below (excluding legacy Azure duplicates already covered by suffix rules).",
        "",
        "Related: [FINOPS_ANALYSIS_VERIFICATION.md](FINOPS_ANALYSIS_VERIFICATION.md), `GET /api/v1/rules/catalog`.",
        "",
        "---",
        "",
    ]

    for provider, family, category, resource_types, family_rules in FAMILIES:
        lines.append(f"## {provider} · {family.replace('-', ' ').title()} (`{category}`)")
        lines.append("")
        lines.append("| Resource type | Rules evaluated |")
        lines.append("| --- | --- |")
        for rt in resource_types:
            res = synthetic(provider, rt)
            rows = evaluate_inventory([res], observed_at=NOW.isoformat(), now=NOW)
            rule_ids = sorted({r["rule_id"] for r in rows})
            if not rule_ids:
                cell = "*(none — verify catalog)*"
            else:
                cell = "<br>".join(f"**{display_name(rid)}** (`{rid}`)" for rid in rule_ids)
            lines.append(f"| `{rt}` | {cell} |")
        lines.append("")
        lines.append(
            f"**Family rule set** ({len(family_rules)} ids): "
            + ", ".join(f"`{r}`" for r in family_rules)
        )
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Full rule index (display name → id)",
            "",
            "| Display name | rule_id | Providers |",
            "| --- | --- | --- |",
        ]
    )
    rule_providers: dict[str, set[str]] = {}
    for p, _f, _c, _t, rules in FAMILIES:
        for rid in rules:
            rule_providers.setdefault(rid, set()).add(p)
    for rid in sorted(rule_providers):
        prov = ", ".join(sorted(rule_providers[rid]))
        lines.append(f"| {RULE_DISPLAY_NAMES[rid]} | `{rid}` | {prov} |")

    out = ROOT / "docs" / "RESOURCE_ANALYSIS_RULES.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out.relative_to(ROOT)} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
