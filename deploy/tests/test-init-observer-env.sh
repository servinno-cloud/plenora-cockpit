#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM
mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/init-observer-env.sh" "$test_root/deploy/"
cp "$source_root/.env.observer.example" "$source_root/docker-compose.observer.yml" "$test_root/"

cat > "$test_root/bin/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '0123456789abcdef0123456789abcdef01234567'
EOF
cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
[[ "$*" == *'compose --env-file '*'-f '*'/docker-compose.observer.yml config --quiet' ]]
EOF
chmod 700 "$test_root/bin/git" "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"

environment_id='11111111-1111-4111-8111-111111111111'
observer_id='33333333-3333-4333-8333-333333333333'
observer_token='synthetic-observer-token-0000000000000000'
database_url='postgresql://monitor:synthetic@db/plenora'
output="$(printf '%s\n%s\n%s\n%s\n' \
  "$environment_id" "$observer_id" "$observer_token" "$database_url" | \
  bash "$test_root/deploy/init-observer-env.sh" 2>&1)"

[[ "$output" == *'Observer production environment initialized successfully.'* ]]
[[ "$output" != *"$observer_token"* && "$output" != *"$database_url"* ]]
[[ "$(stat -c '%a' "$test_root/.env.observer")" == 600 ]]
grep -Fxq 'COCKPIT_INGEST_URL=https://cockpit.plenora.nl' "$test_root/.env.observer"
grep -Fxq 'PLENORA_NETWORK=app_default' "$test_root/.env.observer"
grep -Fxq 'DOCKER_GID=988' "$test_root/.env.observer"
grep -Fxq 'OBSERVER_CONTAINER_CADDY=app-caddy-1' "$test_root/.env.observer"
grep -Fxq 'OBSERVER_CONTAINER_FRONTEND=app-frontend-1' "$test_root/.env.observer"
grep -Fxq 'OBSERVER_CONTAINER_BACKEND=app-backend-1' "$test_root/.env.observer"
grep -Fxq 'OBSERVER_CONTAINER_DB=app-db-1' "$test_root/.env.observer"
grep -Fxq 'OBSERVER_CONTAINER_MAIL_WORKER=app-mail-worker-1' "$test_root/.env.observer"
grep -Fxq "COLLECTOR_ENVIRONMENT_ID=$environment_id" "$test_root/.env.observer"
grep -Fxq "PLENORA_OBSERVER_ID=$observer_id" "$test_root/.env.observer"
grep -Fxq "PLENORA_OBSERVER_TOKEN=$observer_token" "$test_root/.env.observer"
grep -Fxq "PLENORA_MONITOR_DATABASE_URL=$database_url" "$test_root/.env.observer"

if bash "$test_root/deploy/init-observer-env.sh" >/dev/null 2>&1; then
  printf 'existing observer env was overwritten without --force\n' >&2
  exit 1
fi

printf 'observer env bootstrap tests passed\n'
