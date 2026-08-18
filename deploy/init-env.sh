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

postgres_db="plenora_cockpit"
postgres_user="plenora_cockpit"
postgres_password="$(random_hex 32)"
cockpit_secret_key="$(random_hex 48)"
collector_token="$(random_hex 32)"
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
    COLLECTOR_TOKEN) printf 'COLLECTOR_TOKEN=%s\n' "$collector_token" ;;
    COCKPIT_RELEASE) printf 'COCKPIT_RELEASE=%s\n' "$release" ;;
    COCKPIT_MAIL_INTEGRATION_ENABLED) printf '%s\n' 'COCKPIT_MAIL_INTEGRATION_ENABLED=false' ;;
    PLENORA_OBSERVER_ID|PLENORA_OBSERVER_TOKEN) printf '%s=\n' "$key" ;;
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
