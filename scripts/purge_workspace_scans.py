"""Remove saved scan history for configured tenants (operator-only)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings


def main():
    settings = Settings.load()
    if not settings.database_url:
        raise SystemExit('CLOUDSAVER_DATABASE_URL is required (run inside Compose or set URL)')
    import psycopg
    with psycopg.connect(settings.database_url, connect_timeout=10) as db:
        role = db.execute('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        if any(role):
            raise SystemExit('Use the restricted application role')
        for tenant in settings.tenants:
            tid = tenant['tenant_id']
            db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (tid,))
            scans = db.execute('DELETE FROM public.scans WHERE tenant_id=%s RETURNING id', (tid,)).rowcount
            findings = db.execute('DELETE FROM public.waste_findings WHERE tenant_id=%s', (tid,)).rowcount
            cloud = db.execute('DELETE FROM public.cloud_findings WHERE tenant_id=%s', (tid,)).rowcount
            print(f'{tid}: removed {scans} scans, {findings} azure rows, {cloud} cloud rows')


if __name__ == '__main__':
    main()
