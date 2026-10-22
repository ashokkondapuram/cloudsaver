"""Tenant-scoped durable worker state and atomic ingestion transactions."""
from contextlib import contextmanager
from uuid import UUID, uuid5


class JobRepository:
    def __init__(self, database_url):
        import psycopg
        if not database_url:
            raise ValueError('Scheduled scans require CLOUDSAVER_DATABASE_URL')
        from app.store import PostgresStore
        PostgresStore(database_url)
        self.url = database_url
        with psycopg.connect(self.url, connect_timeout=10) as db:
            role = db.execute('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            if role[0] or role[1]:
                raise ValueError('Worker database role must not bypass tenant isolation')
            for table in ('scan_jobs', 'scans', 'tenants', 'subscriptions', 'waste_findings'):
                flags = db.execute('SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)',
                                   ('public.' + table,)).fetchone()
                if not flags or not all(flags):
                    raise ValueError('Apply worker migrations with forced RLS before starting workers')

    @contextmanager
    def transaction(self, tenant_id):
        import psycopg
        with psycopg.connect(self.url, connect_timeout=10) as db:
            db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(UUID(tenant_id)),))
            yield db

    @staticmethod
    def _active(db, tenant_id):
        rows = db.execute('SELECT s.subscription_id FROM public.subscriptions s '
                          'JOIN public.tenants t ON t.tenant_id=s.tenant_id '
                          "WHERE s.tenant_id=%s AND s.active=true AND t.connection_status='connected'",
                          (tenant_id,)).fetchall()
        return [str(row[0]) for row in rows]

    def active_subscriptions(self, tenant_id):
        with self.transaction(tenant_id) as db:
            return self._active(db, tenant_id)

    def plan_tier(self, tenant_id):
        with self.transaction(tenant_id) as db:
            rows = db.execute('SELECT plan_tier FROM organizations WHERE tenant_id=%s', (tenant_id,)).fetchall()
            if len(rows) != 1:
                raise ValueError('An unambiguous provisioned organization is required')
        return rows[0][0]

    def reserve_scheduled_job(self, tenant_id, job_id, minimum_seconds, subscription_ids):
        subscription_ids = [str(UUID(s)) for s in subscription_ids]
        if not 1 <= len(subscription_ids) <= 100 or len(set(subscription_ids)) != len(subscription_ids):
            raise ValueError("Invalid scheduled subscription selection")
        with self.transaction(tenant_id) as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (tenant_id,))
            recent = db.execute("SELECT 1 FROM scan_jobs WHERE tenant_id=%s AND created_at > clock_timestamp() - make_interval(secs => %s) LIMIT 1", (tenant_id, minimum_seconds)).fetchone()
            if recent:
                return False
            db.execute("INSERT INTO scan_jobs(id,tenant_id,status) VALUES (%s,%s,'queued')", (job_id,tenant_id))
            from database.delivery import enqueue
            enqueue(db,tenant_id,'scan',job_id=job_id,payload={'subscription_ids':subscription_ids})
            return True

    def queue_job(self, tenant_id, job_id):
        with self.transaction(tenant_id) as db:
            db.execute("INSERT INTO public.scan_jobs (id,tenant_id,status) VALUES (%s,%s,'queued') ON CONFLICT (id) DO NOTHING",
                       (job_id, tenant_id))

    def get_job(self, tenant_id, job_id):
        with self.transaction(tenant_id) as db:
            row = db.execute('SELECT status,scan_id,attempts FROM public.scan_jobs WHERE id=%s AND tenant_id=%s',
                             (job_id, tenant_id)).fetchone()
        return dict(status=row[0], scan_id=str(row[1]) if row[1] else None, attempts=row[2]) if row else None

    def verify_delivery(self, tenant_id, job_id, subscriptions):
        """Broker arguments must match a previously committed tenant job intent."""
        if not isinstance(subscriptions,list) or not 1<=len(subscriptions)<=100:
            return False
        try:
            normalized=[str(UUID(s)) for s in subscriptions]
            job_id=str(UUID(job_id))
        except (ValueError,TypeError,AttributeError):
            return False
        if len(set(normalized))!=len(normalized):
            return False
        with self.transaction(tenant_id) as db:
            row=db.execute("SELECT payload FROM delivery_events WHERE tenant_id=%s AND job_id=%s AND kind='scan'",(tenant_id,job_id)).fetchone()
            return bool(row and sorted(row[0].get('subscription_ids',[]))==sorted(normalized))

    def start_job(self, tenant_id, job_id, token):
        with self.transaction(tenant_id) as db:
            row = db.execute('SELECT status,attempts FROM public.scan_jobs WHERE id=%s AND tenant_id=%s FOR UPDATE',
                             (job_id, tenant_id)).fetchone()
            if not row:
                raise ValueError('Job does not exist in this workspace')
            if row[0] in ('completed', 'failed'):
                return False
            if row[1] >= 4:
                db.execute("UPDATE public.scan_jobs SET status='failed',error_code='retry_limit',updated_at=now() "
                           'WHERE id=%s AND tenant_id=%s', (job_id, tenant_id))
                return False
            db.execute("UPDATE public.scan_jobs SET status='running',attempts=attempts+1,error_code=NULL,lease_token=%s,updated_at=now() "
                       'WHERE id=%s AND tenant_id=%s', (token, job_id, tenant_id))
            return True

    def fail_job(self, tenant_id, job_id, error_code, final=False, token=None):
        with self.transaction(tenant_id) as db:
            db.execute('UPDATE public.scan_jobs SET status=%s,error_code=%s,updated_at=now() '
                       "WHERE id=%s AND tenant_id=%s AND status NOT IN ('completed','failed') AND (status='queued' OR lease_token=%s)",
                       ('failed' if final else 'queued', error_code, job_id, tenant_id, token))

    def complete_job(self, tenant_id, job_id, scan, subscriptions, *, token, notification_targets=()):
        """Snapshot, normalized findings and job completion commit or roll back together."""
        from psycopg.types.json import Jsonb
        with self.transaction(tenant_id) as db:
            row = db.execute('SELECT status,lease_token FROM public.scan_jobs WHERE id=%s AND tenant_id=%s FOR UPDATE',
                             (job_id, tenant_id)).fetchone()
            if not row:
                raise ValueError('Job does not exist in this workspace')
            if row[0] == 'completed':
                return
            if row[0] != 'running' or str(row[1]) != token:
                raise ValueError('Stale worker cannot commit job results')
            active = set(self._active(db, tenant_id))
            if not set(subscriptions) <= active or any(f['subscription_id'] not in active for f in scan['findings']):
                raise ValueError('Subscription authorization changed during the scan')
            db.execute('INSERT INTO public.scans (id,tenant_id,timestamp,payload) VALUES (%s,%s,%s,%s) '
                       'ON CONFLICT (id) DO NOTHING',
                       (scan['scan_id'], tenant_id, scan['timestamp'], Jsonb(scan)))
            for finding in scan['findings']:
                finding_id = uuid5(UUID(job_id), finding['resource_id'].lower() + '|' + finding['rule_id'])
                db.execute('INSERT INTO public.waste_findings '
                           '(id,tenant_id,subscription_id,resource_id,resource_name,resource_type,resource_group,'
                           'rule_id,severity,details,evidence,estimated_monthly_waste_usd,observed_at,scan_id) '
                           'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING',
                           (finding_id, tenant_id, finding['subscription_id'], finding['resource_id'],
                            finding['resource_name'], finding['resource_type'], finding['resource_group'],
                            finding['rule_id'], finding['severity'], finding['details'],
                            Jsonb({'scan_id': scan['scan_id'], 'mode': scan['mode']}),
                            finding['estimated_monthly_waste_usd'], scan['timestamp'], scan['scan_id']))
            db.execute("UPDATE public.scan_jobs SET status='completed',scan_id=%s,error_code=NULL,updated_at=now() "
                       'WHERE id=%s AND tenant_id=%s', (scan['scan_id'], job_id, tenant_id))

            from database.delivery import enqueue, notification_payload, audit
            # Completion and delivery intent share this transaction. A worker
            # crash after commit cannot drop the alert or rerun a finished scan.
            for target in notification_targets:
                if target.tenant_id != tenant_id:
                    raise ValueError('Notification target belongs to another tenant')
                enqueue(db,tenant_id,'notification',job_id=job_id,scan_id=scan['scan_id'],target=target,payload=notification_payload(scan))
            if notification_targets:
                db.execute("UPDATE scan_jobs SET notification_status='queued' WHERE id=%s AND tenant_id=%s",(job_id,tenant_id))
            dispatched=db.execute("UPDATE delivery_events SET status='delivered',error_code=NULL,lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE tenant_id=%s AND kind='scan' AND job_id=%s AND status<>'delivered' RETURNING id",(tenant_id,job_id)).fetchall()
            for (event_id,) in dispatched:
                audit(db,tenant_id,event_id,'scan_completed')

    def mark_notification(self, tenant_id, job_id, status):
        if status not in ('sent', 'failed'):
            raise ValueError('Invalid notification status')
        with self.transaction(tenant_id) as db:
            db.execute('UPDATE public.scan_jobs SET notification_status=%s,updated_at=now() WHERE id=%s AND tenant_id=%s',
                       (status, job_id, tenant_id))
