#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
sql_file="$script_dir/sql/create-monitoring-role.sql"
container="app-db-1"
password=""
confirmation=""
command_output=""
role_created=false
completed=false

database_psql() {
  docker exec -i "$container" sh -lc \
    'database_user=${POSTGRES_USER:-postgres}; database_name=${POSTGRES_DB:-$database_user}; \
     exec psql -v ON_ERROR_STOP=1 -U "$database_user" -d "$database_name" "$@"' \
    sh "$@"
}

cleanup() {
  local original_status=$?
  trap - EXIT HUP INT TERM
  if [[ "$role_created" == true && "$completed" != true ]]; then
    database_psql -c \
      'BEGIN; DROP OWNED BY plenora_cockpit_monitor; DROP ROLE plenora_cockpit_monitor; COMMIT;' \
      >/dev/null 2>&1 || true
  fi
  unset password confirmation command_output
  exit "$original_status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

for command in docker grep; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done
[[ -r "$sql_file" ]] || { printf 'Monitoring role SQL is missing.\n' >&2; exit 1; }
[[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" == true ]] || {
  printf 'Production database container app-db-1 is not running.\n' >&2
  exit 1
}

existing="$(database_psql -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname = 'plenora_cockpit_monitor'")"
if [[ "$existing" == 1 ]]; then
  printf 'Monitoring role already exists; refusing to modify it.\n' >&2
  exit 1
fi

if ! IFS= read -r -s -p 'Nieuw monitoringwachtwoord: ' password; then
  printf '\nWachtwoordinvoer is afgebroken.\n' >&2
  exit 1
fi
printf '\n' >&2
if ! IFS= read -r -s -p 'Herhaal monitoringwachtwoord: ' confirmation; then
  printf '\nWachtwoordinvoer is afgebroken.\n' >&2
  exit 1
fi
printf '\n' >&2
if (( ${#password} < 32 )); then
  printf 'Monitoringwachtwoord moet minimaal 32 tekens bevatten.\n' >&2
  exit 1
fi
if [[ "$password" != "$confirmation" ]]; then
  printf 'Wachtwoorden komen niet overeen.\n' >&2
  exit 1
fi
confirmation=""

command_output="$(docker exec -i "$container" sh -lc \
  'database_user=${POSTGRES_USER:-postgres}; database_name=${POSTGRES_DB:-$database_user}; \
   exec psql -v ON_ERROR_STOP=1 -U "$database_user" -d "$database_name" \
    -v monitor_database="$database_name"' < "$sql_file" 2>&1)" || {
  printf 'Monitoringrol kon niet transactioneel worden aangemaakt.\n' >&2
  exit 1
}
role_created=true

command_output="$(printf '%s\n%s\n' "$password" "$password" | \
  database_psql -c '\password plenora_cockpit_monitor' 2>&1)" || {
  printf 'Monitoringwachtwoord kon niet veilig worden ingesteld.\n' >&2
  exit 1
}

export PGPASSWORD="$password"
password=""
command_output="$(docker exec -i -e PGPASSWORD "$container" sh -lc \
  'database_name=${POSTGRES_DB:-postgres}; \
   exec psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U plenora_cockpit_monitor \
    -d "$database_name" -tAc "SHOW default_transaction_read_only"' 2>&1)" || {
  printf 'Monitoringrole-loginverificatie is mislukt.\n' >&2
  exit 1
}
unset PGPASSWORD
if [[ "${command_output//[[:space:]]/}" != on ]]; then
  printf 'Monitoringrole is niet read-only.\n' >&2
  exit 1
fi

completed=true
printf 'Monitoringrol succesvol aangemaakt.\n'
