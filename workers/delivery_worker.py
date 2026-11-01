"""Dispatch platform outbox intents (GitOps PR creation)."""
from __future__ import annotations

import os
import secrets

from app.drift.outbox_store import PlatformOutboxStore
from app.gitops_remediation_flow import GitOpsPullRequestExecutor, build_remediation_package
from app.gitops_ast_mapper import GitOpsAstMapper
from workers.named_lease import NamedRedisLease, gitops_pr_lease_key


def process_gitops_pr_intent(
    intent: dict,
    *,
    outbox: PlatformOutboxStore,
    remediation_store,
    github_executor: GitOpsPullRequestExecutor,
    config,
    file_loader,
    indexed_block_loader,
    lease: NamedRedisLease | None = None,
) -> dict:
    payload = intent["payload"]
    workspace_id = payload["workspace_id"]
    token = secrets.token_hex(8)
    lease_key = gitops_pr_lease_key(intent["idempotency_key"])
    lease = lease or NamedRedisLease(os.getenv("REDIS_URL", "redis://redis:6379/1"), ttl=120)
    if not lease.acquire(lease_key, token):
        return dict(skipped=True, reason="gitops_pr_lease_busy")
    request_id = payload["remediation_request_id"]
    try:
        mapping = GitOpsAstMapper().lookup(payload["canonical_resource_id"]).model_dump()
        target = config.target(workspace_id, payload["target_id"])
        live_file = file_loader(target, mapping)
        block_mapping = (
            dict(mapping, _live_file=live_file)
            if not mapping.get("indexed_block") and mapping.get("start_line")
            else mapping
        )
        indexed_block = indexed_block_loader(block_mapping)
        package = build_remediation_package(
            mapping,
            attribute=payload["attribute"],
            new_token=payload["new_value_token"],
            indexed_block=indexed_block,
            live_file=live_file,
            branch_suffix=payload.get("branch_suffix") or "remediation",
        )
        file_sha = payload["base_file_sha"]
        result = github_executor.execute(target, package, file_sha=file_sha)
        remediation_store.update_status(workspace_id, request_id, "OPEN", result=result)
        outbox.complete(workspace_id, intent["id"])
        return result
    except ValueError as exc:
        if str(exc) == "REPO_DRIFT_REINDEX_REQUIRED":
            remediation_store.update_status(workspace_id, request_id, "REPO_DRIFT_REINDEX_REQUIRED")
            outbox.complete(workspace_id, intent["id"])
            return dict(status="REPO_DRIFT_REINDEX_REQUIRED")
        outbox.fail(workspace_id, intent["id"], "package_invalid")
        raise
    except Exception:
        remediation_store.update_status(workspace_id, request_id, "UNCERTAIN")
        outbox.fail(workspace_id, intent["id"], "vcs_uncertain")
        raise
    finally:
        lease.release(lease_key, token)


def dispatch_gitops_pr(outbox: PlatformOutboxStore, tenant_id: str, **kwargs) -> list[dict]:
    intents = outbox.claim_pending(tenant_id, "GITOPS_CREATE_PR")
    return [process_gitops_pr_intent(item, outbox=outbox, **kwargs) for item in intents]
