FROM postgres:16-alpine
COPY --chmod=0555 init.sh /docker-entrypoint-initdb.d/00-identity.sh
COPY --chmod=0444 bootstrap.sql /opt/cloudsaver/platform-bootstrap.sql
RUN chmod 0755 /opt/cloudsaver
