"""Time-based billing reconciliation; never infer settlement or extend periods from ledger entries."""
import logging
import threading

from identity.config import flag

logger = logging.getLogger('platform.billing.evaluator')


class BillingEvaluator:
    def __init__(self, service, interval=60):
        self.service, self.interval = service, interval
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        if flag('BILLING_ENABLED'):
            self.thread = threading.Thread(target=self.run, name='billing-evaluator', daemon=True)
            self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.service.evaluate_billing()
            except Exception:
                logger.error('Billing reconciliation failed; no settlement or renewal was assumed.')
            self.stopped.wait(self.interval)

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=6)
