"""Pre-merge PR FinOps and policy scorecard (v3 scaffold)."""
from __future__ import annotations

from typing import Any


def score_pull_request(*, plan_json: dict[str, Any] | None, files_changed: list[str]) -> dict[str, Any]:
    terraform = [f for f in files_changed if f.endswith((".tf", ".tofu"))]
    crossplane = [f for f in files_changed if f.endswith((".yaml", ".yml"))]
    monthly_delta = "0.00"
    if plan_json:
        monthly_delta = str(plan_json.get("prior_monthly_cost_delta_usd") or plan_json.get("monthly_delta") or "0.00")
    return dict(
        decision="review_required",
        monthly_amortized_delta_usd=monthly_delta,
        terraform_files=len(terraform),
        crossplane_files=len(crossplane),
        pillar_violations=[],
        surgical_fix_suggestions=[],
        advisory_only=True,
    )


def webhook_comment_body(scorecard: dict[str, Any]) -> str:
    return (
        "## CloudSaver pre-merge FinOps firewall\n\n"
        f"**Decision:** {scorecard['decision']}\n\n"
        f"**30-day amortized delta (USD):** {scorecard['monthly_amortized_delta_usd']}\n\n"
        f"Terraform files: {scorecard['terraform_files']} | Crossplane files: {scorecard['crossplane_files']}\n"
    )
