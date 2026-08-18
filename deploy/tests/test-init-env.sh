#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM

mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/init-env.sh" "$test_root/deploy/init-env.sh"
cp "$source_root/.env.deploy.example" "$test_root/.env.deploy.example"
cp "$source_root/docker-compose.deploy.yml" "$test_root/docker-compose.deploy.yml"

cat > "$test_root/bin/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '0123456789abcdef0123456789abcdef01234567'
EOF
cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${INIT_ENV_DOCKER_CALLS:?}"
[[ "$*" == *'compose --env-file '*'-f '*'/docker-compose.deploy.yml config --quiet' ]]
EOF
chmod 700 "$test_root/bin/git" "$test_root/bin/docker"
export INIT_ENV_DOCKER_CALLS="$test_root/docker.calls"
export PATH="$test_root/bin:$PATH"

output="$(bash "$test_root/deploy/init-env.sh")"
[[ "$output" == 'Cockpit production environment initialized successfully.' ]]
[[ "$(stat -c '%a' "$test_root/.env.deploy")" == '600' ]]

set -a
source "$test_root/.env.deploy"
set +a
[[ "$POSTGRES_PASSWORD" =~ ^[0-9a-f]{64}$ ]]
[[ "$COCKPIT_SECRET_KEY" =~ ^[0-9a-f]{96}$ ]]
[[ "$COLLECTOR_TOKEN" =~ ^[0-9a-f]{64}$ ]]
[[ "$DATABASE_URL" == "postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@cockpit-db:5432/${POSTGRES_DB}" ]]
[[ "$COCKPIT_RELEASE" == '0123456789abcdef0123456789abcdef01234567' ]]
[[ "$COCKPIT_MAIL_INTEGRATION_ENABLED" == 'false' ]]
[[ -z "$PLENORA_OBSERVER_ID" && -z "$PLENORA_OBSERVER_TOKEN" ]]
[[ "$(wc -l < "$test_root/docker.calls")" -eq 2 ]]

before="$(sha256sum "$test_root/.env.deploy")"
if bash "$test_root/deploy/init-env.sh" >/dev/null 2>&1; then
  printf 'existing-file refusal failed\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$before" ]]
bash "$test_root/deploy/init-env.sh" --force >/dev/null
[[ "$(stat -c '%a' "$test_root/.env.deploy")" == '600' ]]

printf 'init-env tests passed\n'
