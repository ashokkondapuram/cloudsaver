"""tenant-service projector: applies the platform directory change feed to the tenant registry."""
import logging
import os
import threading
import time

logger = logging.getLogger('cloudsaver.directory')
WORKSPACE_CHANGES = ('workspace_upserted', 'workspace_deleted', 'entitlements_changed')


class DirectoryProjector:
    def __init__(self, registry, client, *, interval=None, clock=time.time):
        self.registry, self.client = registry, client
        self.interval = float(interval if interval is not None else os.getenv('CLOUDSAVER_DIRECTORY_POLL_SECONDS', '5'))
        self.clock = clock
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.last_success = None
        self.thread = None

    def resync(self):
        response = self.client.get('/internal/v1/directory/snapshot')
        if response.status_code != 200:
            raise RuntimeError('Directory snapshot unavailable')
        data = response.json()
        for snap in data['workspaces']:
            self.registry.apply_snapshot(snap)
        self.registry.deactivate_missing([s['tenant_id'] for s in data['workspaces'] if s['status'] != 'deleted'])
        self.registry.apply_platform(data['platform'])
        self.registry.set_projection_cursor(data['seq'])
        logger.info('Directory projection resynchronized workspaces=%s', len(data['workspaces']))

    def apply(self, change):
        """Workspace snapshots are complete and carry the plan block, so entitlement changes apply the same way."""
        if change['change_type'] == 'platform_updated':
            self.registry.apply_platform(change['snapshot'])
        elif change['change_type'] in WORKSPACE_CHANGES:
            self.registry.apply_snapshot(change['snapshot'])
        else:
            logger.info('Ignoring unknown directory change type')

    def run_once(self):
        """Apply every pending change; returns the number applied."""
        with self.registry.projection_transaction() as acquired:
            if not acquired:return 0
            applied = 0
            while True:
                cursor = self.registry.projection_cursor()
                response = self.client.get('/internal/v1/directory/changes', params={'after': cursor, 'limit': 500})
                if response.status_code == 410:
                    self.resync()
                    return applied
                if response.status_code != 200:
                    raise RuntimeError('Directory change feed unavailable')
                items = response.json()['items']
                for change in items:
                    self.apply(change)
                    self.registry.set_projection_cursor(change['seq'])
                    applied += 1
                if len(items) < 500:
                    self.registry.set_projection_cursor(self.registry.projection_cursor())
                    self.last_success = self.clock()
                    return applied

    def lag_seconds(self):
        return None if self.last_success is None else max(0.0, self.clock() - self.last_success)

    def _loop(self):
        delay = self.interval
        while not self.stopped.is_set():
            try:
                self.run_once()
                delay = self.interval
            except Exception:
                logger.warning('Directory projection failed; retrying')
                delay = min(max(delay * 2, 1), 60)
            self.wake.wait(delay)
            self.wake.clear()

    def nudge(self):
        self.wake.set()

    def start(self):
        self.thread = threading.Thread(target=self._loop, name='directory-projector', daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.stopped.set()
        self.wake.set()
