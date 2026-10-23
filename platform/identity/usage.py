"""In-memory usage and failure aggregation, flushed in bulk so floods don't amplify writes."""
import logging
import threading
import time
from collections import defaultdict

logger = logging.getLogger('cloudsaver.identity')


class UsageRecorder:
    def __init__(self, clock=None, last_used_interval=60):
        from identity.domain import utcnow
        self.now = clock or utcnow
        self._lock = threading.Lock()
        self._usage = defaultdict(lambda: [0, 0, None])
        self._failures = defaultdict(int)
        self._last_used = {}
        self._last_written = {}
        self.last_used_interval = last_used_interval

    def success(self, key_id, ip):
        now = self.now()
        with self._lock:
            item = self._usage[(key_id, now.replace(minute=0, second=0, microsecond=0), ip)]
            item[0] += 1
            item[2] = now
            self._last_used[key_id] = (now, ip)

    def failure(self, ip, reason, caller, *, key_id=None, tenant_id=None):
        now = self.now()
        with self._lock:
            if key_id:
                item = self._usage[(key_id, now.replace(minute=0, second=0, microsecond=0), ip)]
                item[1] += 1
                item[2] = now
            self._failures[(now.replace(second=0, microsecond=0), ip, key_id or '', tenant_id, reason, caller)] += 1

    def drain(self):
        monotonic = time.monotonic()
        with self._lock:
            usage = [(k, h, ip, s, f, seen) for (k, h, ip), (s, f, seen) in self._usage.items()]
            failures = [(m, ip, k, t, r, c, n) for (m, ip, k, t, r, c), n in self._failures.items()]
            last_used = {}
            for key_id, value in self._last_used.items():
                if monotonic - self._last_written.get(key_id, -1e9) >= self.last_used_interval:
                    last_used[key_id] = value
                    self._last_written[key_id] = monotonic
            for key_id in last_used:
                self._last_used.pop(key_id, None)
            self._usage.clear()
            self._failures.clear()
        return usage, failures, last_used

    def flush(self, store):
        usage, failures, last_used = self.drain()
        if not (usage or failures or last_used):
            return
        try:
            with store.transaction() as tx:
                tx.record_usage(usage, failures, last_used)
        except Exception:
            logger.warning('Identity usage flush failed; %s rows dropped', len(usage) + len(failures))


class Flusher(threading.Thread):
    def __init__(self, recorder, store, interval=30):
        super().__init__(daemon=True, name='identity-usage-flusher')
        self.recorder, self.store, self.interval = recorder, store, interval
        self.stopped = threading.Event()

    def run(self):
        while not self.stopped.wait(self.interval):
            self.recorder.flush(self.store)

    def stop(self):
        self.stopped.set()
        self.recorder.flush(self.store)
