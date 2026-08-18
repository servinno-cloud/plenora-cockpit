#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
template="$repo_root/.env.deploy.example"
target="$repo_root/.env.deploy"
compose_file="$repo_root/docker-compose.deploy.yml"
force=false
temporary=""
backup=""
had_existing=false

cleanup() {
  if [[ -n "$temporary" ]]; then
    rm -f -- "$temporary"
  fi
  if [[ -n "$backup" ]]; then
    rm -f -- "$backup"
  fi
}
trap cleanup EXIT HUP INT TERM

usage() {
  printf 'Usage: bash deploy/init-env.sh [--force]\n'
}

case "${1:-}" in
  "") ;;
  --force) force=true ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  usage >&2
  exit 2
fi

for command in git docker mktemp chmod mv; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  fi
done
if [[ ! -r "$template" || ! -f "$compose_file" ]]; then
  printf 'Deployment template or Compose file is missing.\n' >&2
  exit 1
fi
if [[ -e "$target" && "$force" != true ]]; then
  printf '.env.deploy already exists; refusing to overwrite it. Use --force explicitly.\n' >&2
  exit 1
fi
if [[ -e "$target" ]]; then
  had_existing=true
  backup="$(mktemp "$repo_root/.env.deploy.backup.XXXXXX")"
  cp -- "$target" "$backup"
  chmod 600 "$backup"
fi

random_hex() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  elif [[ -r /dev/urandom ]] && command -v od >/dev/null 2>&1; then
    od -An -N "$bytes" -tx1 /dev/urandom | tr -d ' \n'
  else
    printf 'No cryptographically secure random source is available.\n' >&2
    return 1
  fi
}

env_value() {
  local file="$1"
  local wanted="$2"
  local line key
  [[ -r "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    key="${line%%=*}"
    if [[ "$key" == "$wanted" ]]; then
      printf '%s' "${line#*=}"
      return 0
    fi
  done < "$file"
}

existing_or_random_hex() {
  local key="$1"
  local bytes="$2"
  local value=""
  if [[ "$had_existing" == true ]]; then
    value="$(env_value "$backup" "$key")"
  fi
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    random_hex "$bytes"
  fi
}

uuid_v4() {
  local raw
  raw="$(random_hex 16)"
  printf '%s-%s-4%s-8%s-%s\n' \
    "${raw:0:8}" "${raw:8:4}" "${raw:13:3}" "${raw:17:3}" "${raw:20:12}"
}

existing_monitoring_value() {
  local canonical="$1"
  local legacy="$2"
  local value=""
  if [[ "$had_existing" == true ]]; then
    value="$(env_value "$backup" "$canonical")"
    if [[ -z "$value" && -n "$legacy" ]]; then
      value="$(env_value "$backup" "$legacy")"
    fi
  fi
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    uuid_v4
  fi
}

postgres_db="plenora_cockpit"
postgres_user="plenora_cockpit"
postgres_password="$(existing_or_random_hex POSTGRES_PASSWORD 32)"
cockpit_secret_key="$(existing_or_random_hex COCKPIT_SECRET_KEY 48)"
collector_secret="$(existing_or_random_hex COCKPIT_MONITORING_COLLECTOR_SECRET 32)"
if [[ "$had_existing" == true && -z "$(env_value "$backup" COCKPIT_MONITORING_COLLECTOR_SECRET)" ]]; then
  legacy_collector_secret="$(env_value "$backup" COLLECTOR_TOKEN)"
  if [[ -n "$legacy_collector_secret" ]]; then
    collector_secret="$legacy_collector_secret"
  fi
fi
monitoring_environment_id="$(existing_monitoring_value COCKPIT_MONITORING_ENVIRONMENT_ID COLLECTOR_ENVIRONMENT_ID)"
monitoring_collector_id="$(existing_monitoring_value COCKPIT_MONITORING_COLLECTOR_ID COLLECTOR_ID)"
observer_id=""
observer_token=""
if [[ "$had_existing" == true ]]; then
  observer_id="$(env_value "$backup" PLENORA_OBSERVER_ID)"
  observer_token="$(env_value "$backup" PLENORA_OBSERVER_TOKEN)"
fi
if [[ ! "$monitoring_environment_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]] ||
   [[ ! "$monitoring_collector_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]]; then
  printf 'Monitoring identifiers must be valid UUIDv4 values.\n' >&2
  exit 1
fi
if (( ${#collector_secret} < 32 )); then
  printf 'Monitoring collector secret must contain at least 32 characters.\n' >&2
  exit 1
fi
if [[ -n "$observer_id" || -n "$observer_token" ]]; then
  if [[ ! "$observer_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]] ||
     (( ${#observer_token} < 32 )); then
    printf 'Observer identity and 32-character secret must both be valid when configured.\n' >&2
    exit 1
  fi
fi
release="$(git -C "$repo_root" rev-parse --verify HEAD)"
database_url="postgresql+psycopg://${postgres_user}:${postgres_password}@cockpit-db:5432/${postgres_db}"

temporary="$(mktemp "$repo_root/.env.deploy.tmp.XXXXXX")"
while IFS= read -r line || [[ -n "$line" ]]; do
  key="${line%%=*}"
  case "$key" in
    COCKPIT_PUBLIC_URL) printf '%s\n' 'COCKPIT_PUBLIC_URL=https://cockpit.plenora.nl' ;;
    COCKPIT_ALLOWED_ORIGINS) printf '%s\n' 'COCKPIT_ALLOWED_ORIGINS=https://cockpit.plenora.nl' ;;
    COCKPIT_SECRET_KEY) printf 'COCKPIT_SECRET_KEY=%s\n' "$cockpit_secret_key" ;;
    POSTGRES_DB) printf 'POSTGRES_DB=%s\n' "$postgres_db" ;;
    POSTGRES_USER) printf 'POSTGRES_USER=%s\n' "$postgres_user" ;;
    POSTGRES_PASSWORD) printf 'POSTGRES_PASSWORD=%s\n' "$postgres_password" ;;
    DATABASE_URL) printf 'DATABASE_URL=%s\n' "$database_url" ;;
    COCKPIT_MONITORING_COLLECTOR_SECRET) printf 'COCKPIT_MONITORING_COLLECTOR_SECRET=%s\n' "$collector_secret" ;;
    COCKPIT_MONITORING_COLLECTOR_ID) printf 'COCKPIT_MONITORING_COLLECTOR_ID=%s\n' "$monitoring_collector_id" ;;
    COCKPIT_MONITORING_ENVIRONMENT_ID) printf 'COCKPIT_MONITORING_ENVIRONMENT_ID=%s\n' "$monitoring_environment_id" ;;
    COCKPIT_RELEASE) printf 'COCKPIT_RELEASE=%s\n' "$release" ;;
    COCKPIT_MAIL_INTEGRATION_ENABLED) printf '%s\n' 'COCKPIT_MAIL_INTEGRATION_ENABLED=false' ;;
    PLENORA_OBSERVER_ID) printf 'PLENORA_OBSERVER_ID=%s\n' "$observer_id" ;;
    PLENORA_OBSERVER_TOKEN) printf 'PLENORA_OBSERVER_TOKEN=%s\n' "$observer_token" ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$template" > "$temporary"
chmod 600 "$temporary"

docker compose --env-file "$temporary" -f "$compose_file" config --quiet
mv -f -- "$temporary" "$target"
temporary=""
chmod 600 "$target"
if ! docker compose --env-file "$target" -f "$compose_file" config --quiet; then
  if [[ "$had_existing" == true ]]; then
    mv -f -- "$backup" "$target"
    backup=""
  else
    rm -f -- "$target"
  fi
  printf 'Generated deployment configuration is invalid.\n' >&2
  exit 1
fi

printf 'Cockpit production environment initialized successfully.\n'
