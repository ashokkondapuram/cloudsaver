#!/bin/sh
# token-db roles: identity_owner runs migrations, identity_app is the unprivileged runtime role,
# identity_retention (NOLOGIN) deletes expired usage rows through SET ROLE from identity_owner.
set -eu
: "${IDENTITY_DB_OWNER_PASSWORD:?Set IDENTITY_DB_OWNER_PASSWORD}"
: "${IDENTITY_DB_APP_PASSWORD:?Set IDENTITY_DB_APP_PASSWORD}"
reset_passwords=false
case "${1:-}" in
  '') ;;
  --reset-passwords) reset_passwords=true ;;
  *) echo 'Usage: init.sh [--reset-passwords]' >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo 'Usage: init.sh [--reset-passwords]' >&2
  exit 2
fi
# psql reads secrets from its environment; no password is put in argv or stdout.
psql --username "$POSTGRES_USER" --dbname postgres --set=ON_ERROR_STOP=1 \
  --set=reset_passwords="$reset_passwords" --file=/opt/cloudsaver/platform-bootstrap.sql
psql --username "$POSTGRES_USER" --dbname identity --set=ON_ERROR_STOP=1 <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
SQL
if [ "$reset_passwords" = true ]; then
  echo 'Platform database role passwords aligned with container environment. Database records retained.'
else
  echo 'Platform database initialized; existing role passwords preserved.'
fi
