#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
sql_file="$script_dir/sql/create-monitoring-role.sql"
provision_file="$repo_root/.observer-database.provision"
container="app-db-1"
password=""
command_output=""
database_name=""
temporary=""
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
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  unset password command_output database_name PGPASSWORD
  exit "$original_status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

for command in docker grep mktemp chmod mv openssl; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done
[[ -r "$sql_file" ]] || { printf 'Monitoring role SQL is missing.\n' >&2; exit 1; }
[[ ! -e "$provision_file" ]] || {
  printf 'Database provisioningbestand bestaat al; consumeer het eerst.\n' >&2
  exit 1
}
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

password="$(openssl rand -hex 16)"
[[ "$password" =~ ^[0-9a-f]{32}$ ]] || {
  printf 'Veilige wachtwoordgeneratie is mislukt.\n' >&2
  exit 1
}
database_name="$(docker exec -i "$container" sh -lc \
  'printf %s "${POSTGRES_DB:-${POSTGRES_USER:-postgres}}"')"
[[ "$database_name" =~ ^[0-9A-Za-z_.-]+$ ]] || {
  printf 'Database name is niet URL-veilig.\n' >&2
  exit 1
}

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
if [[ "${command_output//[[:space:]]/}" != on ]]; then
  printf 'Monitoringrole is niet read-only.\n' >&2
  exit 1
fi

temporary="$(mktemp "$repo_root/.observer-database.provision.tmp.XXXXXX")"
printf 'PLENORA_MONITOR_DATABASE_URL=postgresql://plenora_cockpit_monitor:%s@app-db-1:5432/%s\n' \
  "$PGPASSWORD" "$database_name" > "$temporary"
chmod 600 "$temporary"
mv -- "$temporary" "$provision_file"
temporary=""
chmod 600 "$provision_file"
unset PGPASSWORD
completed=true
printf 'Monitoringrol succesvol aangemaakt.\n'
