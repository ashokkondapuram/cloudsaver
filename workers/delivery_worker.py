"""Dispatch platform outbox intents (GitOps PR creation)."""
from __future__ import annotations

import json
import os
import secrets

from app.drift.outbox_store import OutboxConflict, PlatformOutboxStore

try:
    from pydantic import ValidationError
except ImportError:  # pragma: no cover
    class ValidationError(Exception):
        pass

# Transient errors from a flaky upstream (e.g. a VCS 502 returning an HTML body instead of
# JSON, or a response that fails schema validation) must be retried, not treated as the
# terminal "package_invalid" outcome.
TRANSIENT_VALUE_ERRORS = (json.JSONDecodeError, ValidationError)
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
    mapper: GitOpsAstMapper | None = None,
) -> dict:
    payload = intent["payload"]
    workspace_id = payload["workspace_id"]
    token = secrets.token_hex(8)
    lease_key = gitops_pr_lease_key(intent["idempotency_key"])
    lease = lease or NamedRedisLease(os.getenv("REDIS_URL", "redis://redis:6379/1"), ttl=120)
    if not lease.acquire(lease_key, token):
        outbox.release_to_pending(
            workspace_id, intent["id"], intent["lease_owner"], intent["lease_fence"]
        )
        return dict(skipped=True, reason="gitops_pr_lease_busy")
    request_id = payload["remediation_request_id"]
    try:
        outbox.renew_lease(workspace_id, intent["id"], intent["lease_owner"], intent["lease_fence"])
        mapping = (mapper or GitOpsAstMapper()).lookup(payload["canonical_resource_id"]).model_dump()
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
        outbox.require_lease(workspace_id, intent["id"], intent["lease_owner"], intent["lease_fence"])
        result = github_executor.execute(target, package, file_sha=file_sha)
        with remediation_store.store.transaction(workspace_id, write=True) as db:
            outbox.complete_in_txn(
                db, workspace_id, intent["id"],
                lease_owner=intent["lease_owner"], lease_fence=intent["lease_fence"],
            )
            remediation_store.update_status_in_txn(db, workspace_id, request_id, "OPEN", result=result)
        return result
    except OutboxConflict:
        raise
    except TRANSIENT_VALUE_ERRORS:
        outbox.fail(
            workspace_id,
            intent["id"],
            "vcs_uncertain",
            lease_owner=intent["lease_owner"],
            lease_fence=intent["lease_fence"],
            recoverable=True,
        )
        remediation_store.update_status(workspace_id, request_id, "UNCERTAIN")
        raise
    except ValueError as exc:
        if str(exc) == "REPO_DRIFT_REINDEX_REQUIRED":
            with remediation_store.store.transaction(workspace_id, write=True) as db:
                outbox.complete_in_txn(
                    db, workspace_id, intent["id"],
                    lease_owner=intent["lease_owner"], lease_fence=intent["lease_fence"],
                )
                remediation_store.update_status_in_txn(
                    db, workspace_id, request_id, "REPO_DRIFT_REINDEX_REQUIRED"
                )
            return dict(status="REPO_DRIFT_REINDEX_REQUIRED")
        outbox.fail(
            workspace_id,
            intent["id"],
            "package_invalid",
            lease_owner=intent["lease_owner"],
            lease_fence=intent["lease_fence"],
            recoverable=False,
        )
        remediation_store.update_status(workspace_id, request_id, "FAILED")
        raise
    except Exception:
        outbox.fail(
            workspace_id,
            intent["id"],
            "vcs_uncertain",
            lease_owner=intent["lease_owner"],
            lease_fence=intent["lease_fence"],
            recoverable=True,
        )
        remediation_store.update_status(workspace_id, request_id, "UNCERTAIN")
        raise
    finally:
        lease.release(lease_key, token)


def dispatch_gitops_pr(outbox: PlatformOutboxStore, tenant_id: str, **kwargs) -> list[dict]:
    worker_id = secrets.token_hex(16)
    intents = outbox.claim_pending(tenant_id, "GITOPS_CREATE_PR", owner=worker_id)
    results = []
    for item in intents:
        try:
            results.append(process_gitops_pr_intent(item, outbox=outbox, **kwargs))
        except Exception as exc:
            results.append(dict(intent_id=item["id"], error=type(exc).__name__))
    return results
