"""Incremental PostgreSQL persistence while a synchronous scan is in flight."""
from __future__ import annotations

import logging

logger = logging.getLogger('cloudsaver.scan_progress')


class ScanProgress:
    """Write running-scan inventory to the database as enrichment completes."""

    def __init__(self, store, workspace, scan_id, timestamp, *, mode, cloud_providers):
        self.store = store
        self.workspace = workspace
        self.scan_id = scan_id
        self.timestamp = timestamp
        self.mode = mode
        self.cloud_providers = cloud_providers
        self._seeded = False
        self._completed = False

    def seed_inventory(self, inventory):
        if self._seeded or not inventory:
            return
        providers = self.cloud_providers or ['azure']
        azure_scopes = len(self.workspace.get('subscription_ids') or [])
        subscriptions_scanned = azure_scopes if 'azure' in providers else 0
        self.store.begin_running_scan(
            self.workspace['tenant_id'],
            self.workspace,
            dict(
                scan_id=self.scan_id,
                timestamp=self.timestamp,
                status='running',
                mode=self.mode,
                cloud_providers=self.cloud_providers,
                subscriptions_scanned=subscriptions_scanned,
                total_items_found=len(inventory),
                inventory=list(inventory),
                findings=[],
            ),
        )
        self._seeded = True
        logger.info(
            'Scan seeded workspace=%s scan_id=%s inventory=%s',
            self.workspace['tenant_id'],
            self.scan_id,
            len(inventory),
        )

    def record_observation(self, observation):
        if not self._seeded:
            return
        self.store.upsert_inventory_observation(
            self.workspace['tenant_id'],
            self.scan_id,
            observation,
            workspace=self.workspace,
            observed_at=self.timestamp,
        )

    def complete(self):
        self._completed = True

    def abandon(self):
        if self._completed or not self._seeded:
            return
        try:
            self.store.abandon_running_scan(self.workspace['tenant_id'], self.scan_id)
        except Exception:
            logger.warning('Could not abandon running scan scan_id=%s', self.scan_id)
