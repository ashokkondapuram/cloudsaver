-- Run through init.sh as the local PostgreSQL administrator. PostgreSQL 16's
-- \getenv avoids putting credentials in command-line arguments or terminal output.
\getenv owner_password IDENTITY_DB_OWNER_PASSWORD
\getenv app_password IDENTITY_DB_APP_PASSWORD

BEGIN;
SELECT pg_advisory_xact_lock(hashtext('cloudsaver.platform.bootstrap'));
SELECT format('CREATE ROLE identity_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L', :'owner_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'identity_owner')
\gexec
SELECT format('CREATE ROLE identity_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'identity_app')
\gexec
SELECT 'CREATE ROLE identity_retention NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'identity_retention')
\gexec

DO $$
BEGIN
    IF EXISTS (
        SELECT FROM pg_roles
        WHERE rolname IN ('identity_owner', 'identity_app', 'identity_retention')
          AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication
               OR (rolname = 'identity_retention' AND rolcanlogin)
               OR (rolname <> 'identity_retention' AND NOT rolcanlogin))
    ) THEN
        RAISE EXCEPTION 'Platform roles have unsafe attributes. Administrator review required; passwords were not changed.';
    END IF;
    IF EXISTS (
        SELECT FROM pg_database
        WHERE datname = 'identity' AND pg_get_userbyid(datdba) <> 'identity_owner'
    ) THEN
        RAISE EXCEPTION 'Existing identity database has an unexpected owner. Administrator review required; passwords were not changed.';
    END IF;
END
$$;

-- Password changes require the explicit recovery flag, never normal startup.
\if :reset_passwords
ALTER ROLE identity_owner PASSWORD :'owner_password';
ALTER ROLE identity_app PASSWORD :'app_password';
\endif
GRANT identity_retention TO identity_owner;
COMMIT;

-- CREATE DATABASE must run outside a transaction. Retain an existing database.
SELECT 'CREATE DATABASE identity OWNER identity_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'identity')
\gexec
REVOKE ALL ON DATABASE identity FROM PUBLIC;
GRANT CONNECT ON DATABASE identity TO identity_app;
