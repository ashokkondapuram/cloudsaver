"""Plan and entitlements projected from the platform; local Stripe state becomes read-only.

The platform owns plans, subscriptions and payments (CloudSaver 1.3.0). The tenant-service projector writes
the plan block from the directory feed into tenant_registry. Plan codes may be operator-defined, so the
plan_tier checks accept any uppercase code instead of the three built-in tiers.

public.stripe_events and the organizations stripe_* columns stay readable for scripts/export_billing.py,
but the application role can no longer write them. 0014_drop_local_billing (CloudSaver 1.4.0, at least
30 days after the platform billing import is verified) drops them. 0012 is reserved for
0012_drop_registry_keys.
"""

revision = '0013_billing_projection'
down_revision = '0011_registry_projection'
branch_labels = None
depends_on = None

PLAN_CODE = "plan_tier ~ '^[A-Z][A-Z0-9_]{0,15}$'"
BUILT_IN = "plan_tier IN ('STARTER','GROWTH','ENTERPRISE')"


def _drop_plan_checks(op, table):
    names = op.get_bind().exec_driver_sql(
        "SELECT conname FROM pg_constraint WHERE conrelid = %(t)s::regclass AND contype = 'c' "
        "AND pg_get_constraintdef(oid) LIKE '%%plan_tier%%'", {'t': 'public.' + table}).scalars().all()
    for name in names:
        quoted = op.get_bind().exec_driver_sql('SELECT quote_ident(%(n)s)', {'n': name}).scalar()
        op.execute(f'ALTER TABLE public.{table} DROP CONSTRAINT {quoted}')


def upgrade():
    from alembic import op
    op.execute('''ALTER TABLE public.tenant_registry
        ADD COLUMN entitlements jsonb CHECK (entitlements IS NULL OR jsonb_typeof(entitlements) = 'object'),
        ADD COLUMN entitlements_version integer CHECK (entitlements_version IS NULL OR entitlements_version >= 0),
        ADD COLUMN billing_state text CHECK (billing_state IS NULL OR billing_state IN ('active','grace','lapsed','none')),
        ADD COLUMN plan_name text CHECK (plan_name IS NULL OR length(plan_name) BETWEEN 1 AND 60),
        ADD COLUMN current_period_end timestamptz,
        ADD COLUMN grace_ends_at timestamptz,
        ADD COLUMN subscription_plan_name text CHECK (subscription_plan_name IS NULL OR length(subscription_plan_name) BETWEEN 1 AND 60),
        ADD COLUMN manage_billing_url text CHECK (manage_billing_url IS NULL OR
            (manage_billing_url LIKE 'https://%' AND length(manage_billing_url) <= 2048))''')
    for table, name in (('tenant_registry', 'ck_tenant_registry_plan_code'), ('organizations', 'ck_organizations_plan_tier')):
        _drop_plan_checks(op, table)
        op.execute(f'ALTER TABLE public.{table} ADD CONSTRAINT {name} CHECK ({PLAN_CODE})')
    # Read-only local billing: inserts and updates now come only from the platform, never CloudSaver.
    op.execute('REVOKE INSERT, UPDATE, DELETE ON public.stripe_events FROM cloudsaver_app')
    op.execute('REVOKE INSERT, UPDATE ON public.organizations FROM cloudsaver_app')
    op.execute('GRANT INSERT (id, tenant_id, name, plan_tier, created_at), UPDATE (name, plan_tier) '
               'ON public.organizations TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.execute('REVOKE INSERT (id, tenant_id, name, plan_tier, created_at), UPDATE (name, plan_tier) '
               'ON public.organizations FROM cloudsaver_app')
    op.execute('GRANT INSERT, UPDATE ON public.organizations TO cloudsaver_app')
    op.execute('GRANT INSERT ON public.stripe_events TO cloudsaver_app')
    # Fails if a custom plan code is stored; reassign those workspaces to a built-in tier first.
    for table, name in (('tenant_registry', 'ck_tenant_registry_plan_code'), ('organizations', 'ck_organizations_plan_tier')):
        op.execute(f'ALTER TABLE public.{table} DROP CONSTRAINT {name}')
        op.execute(f'ALTER TABLE public.{table} ADD CONSTRAINT {name} CHECK ({BUILT_IN})')
    op.execute('ALTER TABLE public.tenant_registry DROP COLUMN manage_billing_url, DROP COLUMN subscription_plan_name, '
               'DROP COLUMN grace_ends_at, DROP COLUMN current_period_end, DROP COLUMN plan_name, '
               'DROP COLUMN billing_state, DROP COLUMN entitlements_version, DROP COLUMN entitlements')
