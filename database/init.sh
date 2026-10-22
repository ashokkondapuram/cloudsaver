#!/bin/sh
set -eu
: "${CLOUDSAVER_DB_PASSWORD:?Set CLOUDSAVER_DB_PASSWORD}"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 --set=app_password="$CLOUDSAVER_DB_PASSWORD" <<'SQL'
CREATE ROLE cloudsaver_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
SQL
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 --file=/opt/cloudsaver/001_schema.sql
