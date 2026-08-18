#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM

mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/rotate-collector-secret.sh" "$test_root/deploy/"
cp "$source_root/docker-compose.deploy.yml" "$test_root/"
old_secret='synthetic-old-collector-secret-0000000000000000'
new_secret='abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd'
cat > "$test_root/.env.deploy" <<EOF
COCKPIT_MONITORING_ENVIRONMENT_ID=11111111-1111-4111-8111-111111111111
COCKPIT_MONITORING_COLLECTOR_ID=22222222-2222-4222-8222-222222222222
COCKPIT_MONITORING_COLLECTOR_SECRET=$old_secret
EOF
chmod 600 "$test_root/.env.deploy"
printf '%s' "$old_secret" > "$test_root/database-secret"
printf '%s' '73' > "$test_root/sequence"

cat > "$test_root/bin/openssl" <<EOF
#!/usr/bin/env bash
printf '%s\n' '$new_secret'
EOF
cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
[[ "$*" != *"${COCKPIT_ROTATION_CURRENT_SECRET:-not-present}"* ]]
[[ "$*" != *"${COCKPIT_ROTATION_NEW_SECRET:-not-present}"* ]]
[[ "$*" != *"${COCKPIT_ROTATION_CANDIDATE_SECRET:-not-present}"* ]]
if [[ "$*" == *'config --quiet'* ]]; then exit 0; fi
if [[ "$*" == *'ps --status running --services'* ]]; then
  printf '%s\n' cockpit-backend
  exit 0
fi
if [[ "$*" == *'verify-collector-secret'* ]]; then
  [[ "${COCKPIT_ROTATION_CANDIDATE_SECRET:?}" == "$(<"$ROTATION_DB_SECRET")" ]]
  exit
fi
if [[ "$*" == *'rotate-collector-secret'* ]]; then
  [[ "${COCKPIT_ROTATION_CURRENT_SECRET:?}" == "$(<"$ROTATION_DB_SECRET")" ]]
  printf '%s' "${COCKPIT_ROTATION_NEW_SECRET:?}" > "$ROTATION_DB_SECRET"
  exit 0
fi
if [[ "$*" == *'up -d --wait --no-deps --force-recreate cockpit-backend'* ]]; then
  if [[ "${ROTATION_FAIL_RECREATE:-false}" == true ]]; then exit 1; fi
  exit 0
fi
if [[ "$*" == *'up -d --no-deps --force-recreate cockpit-collector'* ]]; then
  printf '%s\n' "$*" >> "$ROTATION_RECREATE_CALLS"
  if [[ "${ROTATION_FAIL_RECREATE:-false}" == true ]]; then exit 1; fi
  exit 0
fi
exit 2
EOF
chmod 700 "$test_root/bin/openssl" "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"
export ROTATION_DB_SECRET="$test_root/database-secret"
export ROTATION_RECREATE_CALLS="$test_root/recreate.calls"

identity_before="$(grep '^COCKPIT_MONITORING_COLLECTOR_ID=' "$test_root/.env.deploy")"
environment_before="$(grep '^COCKPIT_MONITORING_ENVIRONMENT_ID=' "$test_root/.env.deploy")"
sequence_before="$(<"$test_root/sequence")"
output="$(bash "$test_root/deploy/rotate-collector-secret.sh" 2>&1)"

[[ "$output" == 'Collector secret rotated successfully.' ]]
[[ "$output" != *"$old_secret"* && "$output" != *"$new_secret"* ]]
[[ "$(<"$test_root/database-secret")" == "$new_secret" ]]
[[ "$(grep '^COCKPIT_MONITORING_COLLECTOR_SECRET=' "$test_root/.env.deploy")" == "COCKPIT_MONITORING_COLLECTOR_SECRET=$new_secret" ]]
[[ "$(grep -c '^COCKPIT_MONITORING_COLLECTOR_SECRET=' "$test_root/.env.deploy")" -eq 1 ]]
[[ "$(grep '^COCKPIT_MONITORING_COLLECTOR_ID=' "$test_root/.env.deploy")" == "$identity_before" ]]
[[ "$(grep '^COCKPIT_MONITORING_ENVIRONMENT_ID=' "$test_root/.env.deploy")" == "$environment_before" ]]
[[ "$(<"$test_root/sequence")" == "$sequence_before" ]]
[[ "$(stat -c '%a' "$test_root/.env.deploy")" == 600 ]]
[[ "$(wc -l < "$test_root/recreate.calls")" -eq 1 ]]

sed -i "s/^COCKPIT_MONITORING_COLLECTOR_SECRET=.*/COCKPIT_MONITORING_COLLECTOR_SECRET=$old_secret/" \
  "$test_root/.env.deploy"
printf '%s' "$old_secret" > "$test_root/database-secret"
if rollback_output="$(ROTATION_FAIL_RECREATE=true \
  bash "$test_root/deploy/rotate-collector-secret.sh" 2>&1)"; then
  printf 'recreate failure was accepted\n' >&2
  exit 1
fi
[[ "$rollback_output" != *"$old_secret"* && "$rollback_output" != *"$new_secret"* ]]
[[ "$(<"$test_root/database-secret")" == "$old_secret" ]]
[[ "$(grep '^COCKPIT_MONITORING_COLLECTOR_SECRET=' "$test_root/.env.deploy")" == "COCKPIT_MONITORING_COLLECTOR_SECRET=$old_secret" ]]

printf 'collector secret rotation tests passed\n'
