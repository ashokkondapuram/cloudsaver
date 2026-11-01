"""Poll platform_outbox_intents and hand off to domain workers (drift, GitOps PR)."""
from __future__ import annotations


def drift_dispatch_kwargs(store, tenant_id: str, settings=None) -> dict:
    from app.agent_store import AgentRepository
    from app.config import Settings
    from app.drift.baseline_store import BaselineStore
    from app.drift.live_readers import reader_for_signal
    from app.gitops_ast_mapper import GitOpsAstMapper

    settings = settings or Settings.load()
    tenant = next((row for row in settings.tenants if row["tenant_id"] == tenant_id), None)
    if tenant is None:
        return {}
    baseline_store = BaselineStore(store)
    agent_repo = AgentRepository(store)
    return dict(
        baseline_store=baseline_store,
        agent_repo=agent_repo,
        tenant_loader=lambda workspace_id: tenant if workspace_id == tenant_id else {},
        live_reader=lambda signal: reader_for_signal(signal, tenant=tenant)(signal),
        mapper=GitOpsAstMapper.for_tenant(store, tenant_id),
    )


def dispatch_platform_outbox(store, tenant_id: str, *, transport=None, settings=None) -> dict:
    from app.drift.outbox_store import PlatformOutboxStore
    from app.gitops_remediation_loaders import gitops_delivery_kwargs
    from workers.delivery_worker import dispatch_gitops_pr
    from workers.event_drift_worker import dispatch_pending_drift

    outbox = PlatformOutboxStore(store)
    drift = dispatch_pending_drift(
        outbox,
        tenant_id,
        **drift_dispatch_kwargs(store, tenant_id, settings=settings),
    )
    gitops_kwargs = gitops_delivery_kwargs(store, transport=transport)
    if gitops_kwargs is None:
        gitops = dict(skipped=True, reason="gitops_publish_disabled")
    else:
        gitops = dispatch_gitops_pr(outbox, tenant_id, **gitops_kwargs)
    return dict(drift=drift, gitops=gitops)


def dispatch_all_tenant_outboxes(store, settings=None, *, transport=None) -> dict:
    from app.config import Settings

    settings = settings or Settings.load()
    summary = {}
    for tenant in settings.tenants:
        if tenant.get("active") is False:
            continue
        summary[tenant["tenant_id"]] = dispatch_platform_outbox(
            store, tenant["tenant_id"], transport=transport, settings=settings
        )
    return summary
