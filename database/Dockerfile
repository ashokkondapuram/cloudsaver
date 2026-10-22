FROM postgres:16-alpine
# The database user must be able to read initialization files even when the
# source archive was extracted under a private umask on the host.
COPY --chmod=0555 init.sh /docker-entrypoint-initdb.d/00-init.sh
COPY --chmod=0444 001_schema.sql /opt/cloudsaver/001_schema.sql
