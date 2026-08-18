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

cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ROLE_TEST_ARGV"
[[ "$*" != *"$ROLE_TEST_SECRET"* ]]
if [[ "$1" == inspect ]]; then printf '%s\n' true; exit 0; fi
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
  [[ "$first" == "$ROLE_TEST_SECRET" && "$second" == "$ROLE_TEST_SECRET" ]]
  [[ "${ROLE_TEST_FAIL_PASSWORD:-false}" != true ]]
  exit
fi
if [[ "$*" == *'SHOW default_transaction_read_only'* ]]; then
  printf '%s\n' on
  exit 0
fi
exit 2
EOF
chmod 700 "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"
export ROLE_TEST_ARGV="$test_root/argv"
export ROLE_TEST_EVENTS="$test_root/events"
export ROLE_TEST_SECRET='synthetic-monitoring-password-000000000000'

output="$(printf '%s\n%s\n' "$ROLE_TEST_SECRET" "$ROLE_TEST_SECRET" | \
  bash "$test_root/deploy/create-monitoring-role.sh" 2>&1)"
[[ "$output" == *'Monitoringrol succesvol aangemaakt.'* ]]
[[ "$output" != *"$ROLE_TEST_SECRET"* ]]
! grep -Fq "$ROLE_TEST_SECRET" "$ROLE_TEST_ARGV"

if ROLE_TEST_EXISTING=true bash "$test_root/deploy/create-monitoring-role.sh" \
  >/dev/null 2>&1; then
  printf 'existing role was accepted\n' >&2
  exit 1
fi

if printf '%s\n%s\n' "$ROLE_TEST_SECRET" 'different-password-000000000000000' | \
  bash "$test_root/deploy/create-monitoring-role.sh" >/dev/null 2>&1; then
  printf 'password mismatch was accepted\n' >&2
  exit 1
fi

if printf '\n\n' | bash "$test_root/deploy/create-monitoring-role.sh" \
  >/dev/null 2>&1; then
  printf 'empty password was accepted\n' >&2
  exit 1
fi

: > "$ROLE_TEST_EVENTS"
if printf '%s\n%s\n' "$ROLE_TEST_SECRET" "$ROLE_TEST_SECRET" | \
  ROLE_TEST_FAIL_PASSWORD=true bash "$test_root/deploy/create-monitoring-role.sh" \
  >/dev/null 2>&1; then
  printf 'password failure was accepted\n' >&2
  exit 1
fi
grep -Fxq rollback "$ROLE_TEST_EVENTS"

printf 'monitoring role helper tests passed\n'
