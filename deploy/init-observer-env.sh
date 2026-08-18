#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
template="$repo_root/.env.observer.example"
target="$repo_root/.env.observer"
compose_file="$repo_root/docker-compose.observer.yml"
database_provision="$repo_root/.observer-database.provision"
identity_provision="$repo_root/.observer-identity.provision"
force=false
temporary=""
environment_id=""
observer_id=""
observer_token=""
database_url=""

cleanup() {
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  unset environment_id observer_id observer_token database_url
}
trap cleanup EXIT HUP INT TERM

case "${1:-}" in
  "") ;;
  --force) force=true ;;
  *) printf 'Usage: bash deploy/init-observer-env.sh [--force]\n' >&2; exit 2 ;;
esac
(( $# <= 1 )) || exit 2

for command in docker git mktemp chmod mv stat rm id; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done
[[ "$(id -u)" == 0 ]] || {
  printf 'Observer environment provisioning must run as root.\n' >&2
  exit 1
}
[[ -r "$template" && -f "$compose_file" ]] || {
  printf 'Observer template or Compose file is missing.\n' >&2
  exit 1
}
for provision in "$database_provision" "$identity_provision"; do
  [[ -f "$provision" && ! -L "$provision" ]] || {
    printf 'Private provisioningbestand ontbreekt of is ongeldig.\n' >&2
    exit 1
  }
  [[ "$(stat -c '%a:%u' "$provision")" == 600:0 ]] || {
    printf 'Provisioningbestanden moeten root-owned mode 0600 zijn.\n' >&2
    exit 1
  }
done
if [[ -e "$target" && "$force" != true ]]; then
  printf '.env.observer already exists; use --force explicitly.\n' >&2
  exit 1
fi

mapfile -t identity_lines < "$identity_provision"
[[ ${#identity_lines[@]} == 3 ]] || {
  printf 'Observer identity provisioningbestand heeft een ongeldig formaat.\n' >&2
  exit 1
}
[[ "${identity_lines[0]}" == COCKPIT_ENVIRONMENT_ID=* &&
   "${identity_lines[1]}" == PLENORA_OBSERVER_ID=* &&
   "${identity_lines[2]}" == PLENORA_OBSERVER_TOKEN=* ]] || {
  printf 'Observer identity provisioningbestand heeft een ongeldig formaat.\n' >&2
  exit 1
}
environment_id="${identity_lines[0]#COCKPIT_ENVIRONMENT_ID=}"
observer_id="${identity_lines[1]#PLENORA_OBSERVER_ID=}"
observer_token="${identity_lines[2]#PLENORA_OBSERVER_TOKEN=}"
IFS= read -r database_line < "$database_provision"
[[ "$database_line" == PLENORA_MONITOR_DATABASE_URL=* ]] || {
  printf 'Database provisioningbestand heeft een ongeldig formaat.\n' >&2
  exit 1
}
database_url="${database_line#PLENORA_MONITOR_DATABASE_URL=}"

uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
if [[ ! "$environment_id" =~ $uuid_pattern || ! "$observer_id" =~ $uuid_pattern ]]; then
  printf 'Environment and observer identifiers must be UUID values.\n' >&2
  exit 1
fi
if (( ${#observer_token} < 32 )) || [[ "$observer_token" =~ [[:space:]$] ]]; then
  printf 'Observer token must be at least 32 Compose-safe characters.\n' >&2
  exit 1
fi
database_url_pattern='^postgresql(\+psycopg)?://[0-9A-Za-z._~%:/?@=&+-]+$'
if [[ ! "$database_url" =~ $database_url_pattern ]] ||
   [[ "$database_url" =~ [[:space:]$] ]]; then
  printf 'Monitoring DATABASE_URL is invalid or not Compose-safe.\n' >&2
  exit 1
fi

release="$(git -C "$repo_root" rev-parse --verify HEAD)"
temporary="$(mktemp "$repo_root/.env.observer.tmp.XXXXXX")"
while IFS= read -r line || [[ -n "$line" ]]; do
  key="${line%%=*}"
  case "$key" in
    COCKPIT_INGEST_URL) printf '%s\n' 'COCKPIT_INGEST_URL=https://cockpit.plenora.nl' ;;
    COLLECTOR_ENVIRONMENT_ID) printf 'COLLECTOR_ENVIRONMENT_ID=%s\n' "$environment_id" ;;
    PLENORA_OBSERVER_ID) printf 'PLENORA_OBSERVER_ID=%s\n' "$observer_id" ;;
    PLENORA_OBSERVER_TOKEN) printf 'PLENORA_OBSERVER_TOKEN=%s\n' "$observer_token" ;;
    PLENORA_OBSERVER_RELEASE) printf 'PLENORA_OBSERVER_RELEASE=%s\n' "$release" ;;
    PLENORA_MONITOR_DATABASE_URL) printf 'PLENORA_MONITOR_DATABASE_URL=%s\n' "$database_url" ;;
    DOCKER_GID) printf '%s\n' 'DOCKER_GID=988' ;;
    PLENORA_NETWORK) printf '%s\n' 'PLENORA_NETWORK=app_default' ;;
    OBSERVER_CONTAINER_CADDY) printf '%s\n' 'OBSERVER_CONTAINER_CADDY=app-caddy-1' ;;
    OBSERVER_CONTAINER_FRONTEND) printf '%s\n' 'OBSERVER_CONTAINER_FRONTEND=app-frontend-1' ;;
    OBSERVER_CONTAINER_BACKEND) printf '%s\n' 'OBSERVER_CONTAINER_BACKEND=app-backend-1' ;;
    OBSERVER_CONTAINER_DB) printf '%s\n' 'OBSERVER_CONTAINER_DB=app-db-1' ;;
    OBSERVER_CONTAINER_MAIL_WORKER) printf '%s\n' 'OBSERVER_CONTAINER_MAIL_WORKER=app-mail-worker-1' ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$template" > "$temporary"
chmod 600 "$temporary"
docker compose --env-file "$temporary" -f "$compose_file" config --quiet
mv -f -- "$temporary" "$target"
temporary=""
chmod 600 "$target"
rm -f -- "$database_provision" "$identity_provision"
printf 'Observer production environment initialized successfully.\n'
