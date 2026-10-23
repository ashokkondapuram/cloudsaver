#!/bin/sh
# token-db roles: identity_owner runs migrations, identity_app is the unprivileged runtime role,
# identity_retention (NOLOGIN) deletes expired usage rows through SET ROLE from identity_owner.
set -eu
: "${IDENTITY_DB_OWNER_PASSWORD:?Set IDENTITY_DB_OWNER_PASSWORD}"
: "${IDENTITY_DB_APP_PASSWORD:?Set IDENTITY_DB_APP_PASSWORD}"
psql --username "$POSTGRES_USER" --dbname postgres --set=ON_ERROR_STOP=1 \
  --set=owner_password="$IDENTITY_DB_OWNER_PASSWORD" --set=app_password="$IDENTITY_DB_APP_PASSWORD" <<'SQL'
CREATE ROLE identity_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'owner_password';
CREATE ROLE identity_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE ROLE identity_retention NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT identity_retention TO identity_owner;
CREATE DATABASE identity OWNER identity_owner;
REVOKE ALL ON DATABASE identity FROM PUBLIC;
GRANT CONNECT ON DATABASE identity TO identity_app;
SQL
psql --username "$POSTGRES_USER" --dbname identity --set=ON_ERROR_STOP=1 <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
SQL
