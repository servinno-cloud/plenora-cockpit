#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM
mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/provision-observer-identity.sh" "$test_root/deploy/"
cp "$source_root/.env.deploy.example" "$test_root/.env.deploy"
cp "$source_root/docker-compose.deploy.yml" "$test_root/"
environment_id='11111111-1111-4111-8111-111111111111'
sed -i "s/^COCKPIT_MONITORING_ENVIRONMENT_ID=.*/COCKPIT_MONITORING_ENVIRONMENT_ID=$environment_id/" \
  "$test_root/.env.deploy"
chmod 600 "$test_root/.env.deploy"

cat > "$test_root/bin/id" <<'EOF'
#!/usr/bin/env bash
[[ "$1" == -u ]] && printf '0\n'
EOF
cat > "$test_root/bin/stat" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *'.observer-identity.provision'* ]]; then printf '600:0\n'; else /usr/bin/stat "$@"; fi
EOF
cat > "$test_root/bin/openssl" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == 'rand -hex 16' ]]; then
  printf '0123456789abcdef0123456789abcdef\n'
elif [[ "$*" == 'rand -hex 32' ]]; then
  printf 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789\n'
else
  exit 1
fi
EOF
cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "$IDENTITY_TEST_ARGV"
[[ -z "${COCKPIT_MONITORING_OBSERVER_SECRET:-}" || "$*" != *"$COCKPIT_MONITORING_OBSERVER_SECRET"* ]]
[[ -z "${COCKPIT_ROTATION_CANDIDATE_SECRET:-}" || "$*" != *"$COCKPIT_ROTATION_CANDIDATE_SECRET"* ]]
if [[ "$*" == *'ps --status running -q cockpit-backend'* ]]; then
  printf 'backend-container-id\n'
elif [[ "$*" == *'python -m app.cli seed-monitoring'* ]]; then
  [[ "${IDENTITY_TEST_FAIL_SEED:-false}" != true ]]
  printf '%s|%s\n' "$COCKPIT_MONITORING_OBSERVER_ID" \
    "$COCKPIT_MONITORING_OBSERVER_SECRET" > "$IDENTITY_TEST_DB"
elif [[ "$*" == *'python -m app.cli verify-collector-secret'* ]]; then
  IFS='|' read -r stored_id stored_secret < "$IDENTITY_TEST_DB"
  [[ "$COCKPIT_ROTATION_ENVIRONMENT_ID" == '11111111-1111-4111-8111-111111111111' ]]
  [[ "$COCKPIT_ROTATION_COLLECTOR_ID" == "$stored_id" ]]
  [[ "$COCKPIT_ROTATION_CANDIDATE_SECRET" == "$stored_secret" ]]
elif [[ "$*" == *'config --quiet'* ]]; then
  exit 0
else
  exit 2
fi
EOF
chmod 700 "$test_root/bin/id" "$test_root/bin/stat" "$test_root/bin/openssl" "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"
export IDENTITY_TEST_ARGV="$test_root/argv"
export IDENTITY_TEST_DB="$test_root/db"

output="$(bash "$test_root/deploy/provision-observer-identity.sh" 2>&1)"
bundle="$test_root/.observer-identity.provision"
[[ "$output" == *'private bundle gereed voor overdracht.'* ]]
[[ "$(/usr/bin/stat -c '%a' "$bundle")" == 600 ]]
mapfile -t lines < "$bundle"
[[ "${lines[0]}" == "COCKPIT_ENVIRONMENT_ID=$environment_id" ]]
observer_id="${lines[1]#PLENORA_OBSERVER_ID=}"
observer_token="${lines[2]#PLENORA_OBSERVER_TOKEN=}"
[[ "$observer_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$ ]]
[[ "$observer_token" =~ ^[0-9a-f]{64}$ ]]
[[ "$output" != *"$observer_token"* ]]
! grep -Fq "$observer_token" "$IDENTITY_TEST_ARGV"
grep -Fxq "PLENORA_OBSERVER_ID=$observer_id" "$test_root/.env.deploy"
grep -Fxq "PLENORA_OBSERVER_TOKEN=$observer_token" "$test_root/.env.deploy"
[[ "$(/usr/bin/stat -c '%a' "$test_root/.env.deploy")" == 600 ]]

if IDENTITY_TEST_FAIL_SEED=true bash "$test_root/deploy/provision-observer-identity.sh" \
  >/dev/null 2>&1; then
  printf 'failed seed was accepted\n' >&2
  exit 1
fi
[[ -f "$bundle" ]]
grep -Fxq "PLENORA_OBSERVER_TOKEN=$observer_token" "$bundle"

printf 'observer identity provisioning tests passed\n'
