#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM
mkdir -p "$test_root/deploy/sql" "$test_root/bin"
cp "$source_root/deploy/create-monitoring-role.sh" "$test_root/deploy/"
cp "$source_root/deploy/sql/create-monitoring-role.sql" "$test_root/deploy/sql/"

cat > "$test_root/bin/openssl" <<'EOF'
#!/usr/bin/env bash
[[ "$*" == 'rand -hex 16' ]]
count=0
[[ ! -f "$ROLE_TEST_RANDOM_COUNT" ]] || read -r count < "$ROLE_TEST_RANDOM_COUNT"
count=$((count + 1))
printf '%s\n' "$count" > "$ROLE_TEST_RANDOM_COUNT"
if [[ "$count" == 1 ]]; then
  printf '%s\n' '0123456789abcdef0123456789abcdef'
else
  printf '%s\n' 'fedcba9876543210fedcba9876543210'
fi
EOF
cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ROLE_TEST_ARGV"
if [[ "$1" == inspect ]]; then printf '%s\n' true; exit 0; fi
if [[ "$*" == *'printf %s'*'POSTGRES_DB'* ]]; then printf '%s' plenora; exit 0; fi
if [[ "$*" == *'SELECT 1 FROM pg_roles'* ]]; then
  [[ "${ROLE_TEST_EXISTING:-false}" != true ]] || printf '%s\n' 1
  exit 0
fi
if [[ "$*" == *'DROP OWNED BY plenora_cockpit_monitor'* ]]; then
  printf '%s\n' rollback >> "$ROLE_TEST_EVENTS"
  exit 0
fi
if [[ "$*" == *'monitor_database='* ]]; then
  sed -n '1p' >/dev/null
  [[ "${ROLE_TEST_FAIL_PROVISION:-false}" != true ]]
  exit
fi
if [[ "$*" == *'\password plenora_cockpit_monitor'* ]]; then
  IFS= read -r first
  IFS= read -r second
  [[ "$first" == "$second" && "$first" =~ ^[0-9a-f]{32}$ ]]
  printf '%s\n' "$first" >> "$ROLE_TEST_SECRETS"
  [[ "${ROLE_TEST_FAIL_PASSWORD:-false}" != true ]]
  exit
fi
if [[ "$*" == *'SHOW default_transaction_read_only'* ]]; then
  printf '%s\n' on
  exit 0
fi
exit 2
EOF
chmod 700 "$test_root/bin/docker" "$test_root/bin/openssl"
export PATH="$test_root/bin:$PATH"
export ROLE_TEST_ARGV="$test_root/argv"
export ROLE_TEST_EVENTS="$test_root/events"
export ROLE_TEST_SECRETS="$test_root/secrets"
export ROLE_TEST_RANDOM_COUNT="$test_root/random-count"

output="$(bash "$test_root/deploy/create-monitoring-role.sh" 2>&1)"
[[ "$output" == *'Monitoringrol succesvol aangemaakt.'* ]]
first_secret="$(sed -n '1p' "$ROLE_TEST_SECRETS")"
[[ ${#first_secret} == 32 && "$first_secret" =~ ^[0-9a-f]{32}$ ]]
[[ "$output" != *"$first_secret"* ]]
! grep -Fq "$first_secret" "$ROLE_TEST_ARGV"
[[ "$(stat -c '%a' "$test_root/.observer-database.provision")" == 600 ]]
grep -Fxq "PLENORA_MONITOR_DATABASE_URL=postgresql://plenora_cockpit_monitor:${first_secret}@app-db-1:5432/plenora" \
  "$test_root/.observer-database.provision"

rm -f "$test_root/.observer-database.provision"
output="$(bash "$test_root/deploy/create-monitoring-role.sh" 2>&1)"
second_secret="$(sed -n '2p' "$ROLE_TEST_SECRETS")"
[[ "$second_secret" =~ ^[0-9a-f]{32}$ && "$second_secret" != "$first_secret" ]]
[[ "$output" != *"$second_secret"* ]]
! grep -Fq "$second_secret" "$ROLE_TEST_ARGV"

rm -f "$test_root/.observer-database.provision"
if ROLE_TEST_EXISTING=true bash "$test_root/deploy/create-monitoring-role.sh" \
  >/dev/null 2>&1; then
  printf 'existing role was accepted\n' >&2
  exit 1
fi

: > "$ROLE_TEST_EVENTS"
if ROLE_TEST_FAIL_PASSWORD=true bash "$test_root/deploy/create-monitoring-role.sh" \
  >/dev/null 2>&1; then
  printf 'password failure was accepted\n' >&2
  exit 1
fi
grep -Fxq rollback "$ROLE_TEST_EVENTS"

printf 'monitoring role helper tests passed\n'
