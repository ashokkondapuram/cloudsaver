-- Run as the migration owner. The application role has no schema modification rights.
CREATE TABLE IF NOT EXISTS public.scans (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    timestamp timestamptz NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS scans_owner ON public.scans(tenant_id, timestamp DESC);
ALTER TABLE public.scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON public.scans;
CREATE POLICY tenant_isolation ON public.scans
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
REVOKE ALL ON public.scans FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO cloudsaver_app;
GRANT SELECT, INSERT ON public.scans TO cloudsaver_app;
