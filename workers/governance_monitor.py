"""Continuous local governance reassessment. Never executes cloud actions or sends evidence out."""

import logging, signal, time
from app.config import Settings
from app.enterprise_store import EnterpriseStore
from app.store import Store, PostgresStore
from app.governance_store import Governance
from app.governance_api import latest_observation


def run_once(settings=None):
    settings = settings or Settings.load()
    persistence = EnterpriseStore(settings)
    repo = Governance(persistence)
    store = (
        PostgresStore(settings.database_url)
        if settings.database_url
        else Store(settings.database)
    )
    tenants = (
        settings.registry.all()
        if settings.registry is not None
        else settings.bootstrap_tenants
    )
    checked = failed = 0
    for tenant in tenants:
        try:
            with persistence.transaction(tenant["tenant_id"]) as db:
                ids = db.execute(
                    "SELECT id,payload FROM gov_findings WHERE tenant_id=%s LIMIT 1001",
                    (tenant["tenant_id"],),
                ).fetchall()
            if len(ids) > 1000:
                raise ValueError("Governance monitor bound exceeded")
            from app.enterprise_store import decode

            observations = {
                str(r[0]): latest_observation(
                    store, tenant, dict(id=str(r[0]), payload=decode(r[1]))
                )
                for r in ids
            }
            repo.monitor(
                dict(
                    tenant,
                    subject_id="governance-monitor",
                    subject_type="service_account",
                ),
                observations,
                system=True,
            )
            checked += len(ids)
        except Exception:
            failed += 1
    return dict(findings_checked=checked, failed_workspaces=failed, external_calls=0)


def main():
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopped:
        try:
            logging.warning("Governance monitor: %s", run_once())
        except Exception:
            logging.error(
                "Governance monitor unavailable; operator inspection required"
            )
        for _ in range(60):
            if stopped:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
