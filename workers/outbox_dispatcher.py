"""Poll platform_outbox_intents and hand off to domain workers (drift, GitOps PR)."""
from __future__ import annotations


def dispatch_platform_outbox(store, tenant_id: str, *, transport=None) -> dict:
    from app.drift.outbox_store import PlatformOutboxStore
    from app.gitops_remediation_loaders import gitops_delivery_kwargs
    from workers.delivery_worker import dispatch_gitops_pr
    from workers.event_drift_worker import dispatch_pending_drift

    outbox = PlatformOutboxStore(store)
    drift = dispatch_pending_drift(outbox, tenant_id)
    gitops_kwargs = gitops_delivery_kwargs(store, transport=transport)
    if gitops_kwargs is None:
        gitops = dict(skipped=True, reason="gitops_publish_disabled")
    else:
        gitops = dispatch_gitops_pr(outbox, tenant_id, **gitops_kwargs)
    return dict(drift=drift, gitops=gitops)
