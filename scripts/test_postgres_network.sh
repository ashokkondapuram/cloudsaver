#!/usr/bin/env bash
# Run a product's PostgreSQL integration tests on a disposable, internal-only Docker network.
#
#   scripts/test_postgres_network.sh cloudsaver [pytest args]
#   scripts/test_postgres_network.sh platform [pytest args]
#
# Starts fresh postgres:16-alpine and redis:7-alpine containers on the internal network cs-pgtest (no published
# ports), creates NOSUPERUSER NOBYPASSRLS roles, runs the suite in the test image with the repo mounted read-only,
# then removes the containers and the network. The generated password lives only in this process's environment.
set -euo pipefail

product=${1:?Usage: scripts/test_postgres_network.sh cloudsaver|platform [pytest args]}
shift
case "$product" in
  cloudsaver) workdir=/src ;;
  platform) workdir=/src/platform ;;
  *) echo "Unknown product: $product" >&2; exit 2 ;;
esac
root=$(cd "$(dirname "$0")/.." && pwd)
image=${TEST_IMAGE:-cloudsaver-test:1.0.0}
network=cs-pgtest
suffix=$(openssl rand -hex 4)
pg=cs-pgtest-postgres-$suffix
redis=cs-pgtest-redis-$suffix

POSTGRES_PASSWORD=$(openssl rand -hex 24)
export POSTGRES_PASSWORD POSTGRES_DB=cloudsaver_test

cleanup() {
  docker rm -f "$pg" "$redis" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create --internal "$network" >/dev/null
docker run -d --name "$pg" --network "$network" -e POSTGRES_PASSWORD -e POSTGRES_DB \
  --tmpfs /var/lib/postgresql/data postgres:16-alpine >/dev/null
docker run -d --name "$redis" --network "$network" redis:7-alpine >/dev/null

for _ in $(seq 1 60); do
  docker exec "$pg" pg_isready -U postgres -d cloudsaver_test >/dev/null 2>&1 && break
  sleep 1
done
sleep 1

printf "CREATE ROLE cloudsaver_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '%s';
CREATE ROLE cloudsaver_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '%s';
ALTER DATABASE cloudsaver_test OWNER TO cloudsaver_owner;
GRANT ALL ON SCHEMA public TO cloudsaver_owner;
" "$POSTGRES_PASSWORD" "$POSTGRES_PASSWORD" | docker exec -i "$pg" psql -q -v ON_ERROR_STOP=1 -U postgres -d cloudsaver_test >/dev/null

base="$pg:5432/cloudsaver_test"
export CLOUDSAVER_TEST_PRIVILEGED_URL="postgresql://postgres:$POSTGRES_PASSWORD@$base"
export CLOUDSAVER_TEST_OWNER_URL="postgresql://cloudsaver_owner:$POSTGRES_PASSWORD@$base"
export CLOUDSAVER_TEST_APP_URL="postgresql://cloudsaver_app:$POSTGRES_PASSWORD@$base"
export CLOUDSAVER_TEST_REDIS_URL="redis://$redis:6379/0"

set +e
docker run --rm --network "$network" -v "$root":/src:ro -w "$workdir" -e PYTHONDONTWRITEBYTECODE=1 \
  -e CLOUDSAVER_TEST_PRIVILEGED_URL -e CLOUDSAVER_TEST_OWNER_URL -e CLOUDSAVER_TEST_APP_URL -e CLOUDSAVER_TEST_REDIS_URL \
  "$image" python -m pytest -q -p no:cacheprovider -m postgres "$@"
status=$?
set -e
exit $status
