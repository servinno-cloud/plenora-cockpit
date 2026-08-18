#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
env_file="$repo_root/.env.deploy"
compose_file="$repo_root/docker-compose.deploy.yml"
temporary=""
backup=""
old_secret=""
new_secret=""
environment_id=""
collector_id=""
env_updated=false
db_rotated=false
rolling_back=false

env_value() {
  local wanted="$1"
  local line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    key="${line%%=*}"
    if [[ "$key" == "$wanted" ]]; then
      printf '%s' "${line#*=}"
      return 0
    fi
  done < "$env_file"
}

compose=(docker compose --env-file "$env_file" -f "$compose_file")

rotate_database_secret() {
  export COCKPIT_ROTATION_ENVIRONMENT_ID="$environment_id"
  export COCKPIT_ROTATION_COLLECTOR_ID="$collector_id"
  export COCKPIT_ROTATION_CURRENT_SECRET="$1"
  export COCKPIT_ROTATION_NEW_SECRET="$2"
  "${compose[@]}" exec -T \
    -e COCKPIT_ROTATION_ENVIRONMENT_ID \
    -e COCKPIT_ROTATION_COLLECTOR_ID \
    -e COCKPIT_ROTATION_CURRENT_SECRET \
    -e COCKPIT_ROTATION_NEW_SECRET \
    cockpit-backend python -m app.cli rotate-collector-secret >/dev/null
  unset COCKPIT_ROTATION_CURRENT_SECRET COCKPIT_ROTATION_NEW_SECRET
}

credential_is_valid() {
  export COCKPIT_ROTATION_ENVIRONMENT_ID="$environment_id"
  export COCKPIT_ROTATION_COLLECTOR_ID="$collector_id"
  export COCKPIT_ROTATION_CANDIDATE_SECRET="$1"
  local result=0
  "${compose[@]}" exec -T \
    -e COCKPIT_ROTATION_ENVIRONMENT_ID \
    -e COCKPIT_ROTATION_COLLECTOR_ID \
    -e COCKPIT_ROTATION_CANDIDATE_SECRET \
    cockpit-backend python -m app.cli verify-collector-secret >/dev/null 2>&1 || result=$?
  unset COCKPIT_ROTATION_CANDIDATE_SECRET
  return "$result"
}

write_secret() {
  local replacement="$1"
  local found=false
  temporary="$(mktemp "$repo_root/.env.deploy.tmp.XXXXXX")"
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "${line%%=*}" == "COCKPIT_MONITORING_COLLECTOR_SECRET" ]]; then
      printf 'COCKPIT_MONITORING_COLLECTOR_SECRET=%s\n' "$replacement"
      found=true
    else
      printf '%s\n' "$line"
    fi
  done < "$env_file" > "$temporary"
  if [[ "$found" != true ]]; then
    printf 'Collector secret configuration is missing.\n' >&2
    return 1
  fi
  chmod 600 "$temporary"
  docker compose --env-file "$temporary" -f "$compose_file" config --quiet
  mv -f -- "$temporary" "$env_file"
  temporary=""
  chmod 600 "$env_file"
}

rollback() {
  local original_status=$?
  trap - ERR
  set +e
  rolling_back=true
  if [[ "$env_updated" == true && -n "$backup" ]]; then
    cp -- "$backup" "$env_file"
    chmod 600 "$env_file"
    env_updated=false
  fi
  if [[ "$db_rotated" == true ]]; then
    "${compose[@]}" up -d --wait --no-deps --force-recreate cockpit-backend >/dev/null 2>&1
    rotate_database_secret "$new_secret" "$old_secret" >/dev/null 2>&1
    db_rotated=false
  fi
  "${compose[@]}" up -d --no-deps --force-recreate cockpit-collector >/dev/null 2>&1
  printf 'Collector secret rotation failed; rollback attempted.\n' >&2
  exit "$original_status"
}

cleanup() {
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  [[ -z "$backup" ]] || rm -f -- "$backup"
  unset old_secret new_secret environment_id collector_id
  unset COCKPIT_ROTATION_ENVIRONMENT_ID COCKPIT_ROTATION_COLLECTOR_ID
  unset COCKPIT_ROTATION_CURRENT_SECRET COCKPIT_ROTATION_NEW_SECRET
  unset COCKPIT_ROTATION_CANDIDATE_SECRET
}
trap cleanup EXIT HUP INT TERM
trap rollback ERR

for command in docker openssl mktemp chmod cp mv grep; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done
[[ -r "$env_file" && -f "$compose_file" ]] || {
  printf '.env.deploy or docker-compose.deploy.yml is missing.\n' >&2
  exit 1
}

environment_id="$(env_value COCKPIT_MONITORING_ENVIRONMENT_ID)"
collector_id="$(env_value COCKPIT_MONITORING_COLLECTOR_ID)"
old_secret="$(env_value COCKPIT_MONITORING_COLLECTOR_SECRET)"
uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
if [[ ! "$environment_id" =~ $uuid_pattern ]] ||
   [[ ! "$collector_id" =~ $uuid_pattern ]] || (( ${#old_secret} < 32 )); then
  printf 'Collector rotation configuration is invalid.\n' >&2
  exit 1
fi

"${compose[@]}" ps --status running --services | grep -Fxq cockpit-backend
credential_is_valid "$old_secret"
new_secret="$(openssl rand -hex 32)"
backup="$(mktemp "$repo_root/.env.deploy.rotation-backup.XXXXXX")"
cp -- "$env_file" "$backup"
chmod 600 "$backup"

write_secret "$new_secret"
env_updated=true
rotate_database_secret "$old_secret" "$new_secret"
db_rotated=true
"${compose[@]}" up -d --wait --no-deps --force-recreate cockpit-backend >/dev/null
"${compose[@]}" up -d --no-deps --force-recreate cockpit-collector >/dev/null
credential_is_valid "$new_secret"
if credential_is_valid "$old_secret"; then
  printf 'Old collector credential is unexpectedly still valid.\n' >&2
  false
fi

env_updated=false
db_rotated=false
rm -f -- "$backup"
backup=""
printf 'Collector secret rotated successfully.\n'
