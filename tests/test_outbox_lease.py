"""
Tests for Transactional Outbox and Distributed Lease Manager.
"""
import unittest
from database.outbox import OutboxStore, OutboxStatus
from workers.lease import DistributedLeaseManager, JobLifecycleState

class TestOutboxAndLease(unittest.TestCase):
    def setUp(self):
        self.outbox = OutboxStore()
        self.lease = DistributedLeaseManager(default_ttl_seconds=10)

    def test_outbox_enqueue_and_dispatch(self):
        rec = self.outbox.enqueue("tenant-1", "scan-1", {"summary": "test alert"})
        self.assertEqual(rec.status, OutboxStatus.PENDING)
        pending = self.outbox.fetch_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].event_id, rec.event_id)

        self.outbox.mark_dispatched(rec.event_id)
        self.assertEqual(self.outbox.fetch_pending(), [])

    def test_outbox_retry_and_dead_letter(self):
        rec = self.outbox.enqueue("tenant-2", "scan-2", {"alert": "error"}, max_attempts=2)
        self.outbox.mark_failed(rec.event_id, "HTTP 500 error")
        self.assertEqual(rec.attempts, 1)
        self.assertEqual(rec.status, OutboxStatus.FAILED)

        self.outbox.mark_failed(rec.event_id, "HTTP 500 error again")
        self.assertEqual(rec.attempts, 2)
        self.assertEqual(rec.status, OutboxStatus.DEAD_LETTER)

    def test_distributed_lease_acquisition_and_release(self):
        key = "cloudsaver:lease:sub-123"
        self.assertTrue(self.lease.acquire_lease(key, "worker-A", ttl_seconds=5))
        # Other worker fails to acquire held lease
        self.assertFalse(self.lease.acquire_lease(key, "worker-B", ttl_seconds=5))
        # Same worker re-entrant renewal succeeds
        self.assertTrue(self.lease.renew_lease(key, "worker-A", ttl_seconds=10))
        # Release allows another worker to acquire
        self.assertTrue(self.lease.release_lease(key, "worker-A"))
        self.assertTrue(self.lease.acquire_lease(key, "worker-B", ttl_seconds=5))

    def test_cooperative_cancellation_and_job_lifecycle(self):
        job_id = "job-xyz-789"
        self.lease.update_job_state(job_id, JobLifecycleState.SCANNING_ARG)
        self.assertEqual(self.lease.get_job_state(job_id), JobLifecycleState.SCANNING_ARG)

        self.assertFalse(self.lease.is_cancelled(job_id))
        self.lease.request_cancellation(job_id)
        self.assertTrue(self.lease.is_cancelled(job_id))
        self.assertEqual(self.lease.get_job_state(job_id), JobLifecycleState.CANCELLED)

if __name__ == '__main__':
    unittest.main()
