#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
env_file="$repo_root/.env.deploy"
compose_file="$repo_root/docker-compose.deploy.yml"
bundle="$repo_root/.observer-identity.provision"
temporary=""
environment_id=""
observer_id=""
observer_token=""

cleanup() {
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  unset environment_id observer_id observer_token
}
trap cleanup EXIT HUP INT TERM

for command in docker openssl mktemp chmod mv stat id; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done
[[ "$(id -u)" == 0 ]] || {
  printf 'Observer identity provisioning must run as root.\n' >&2
  exit 1
}
[[ -f "$env_file" && ! -L "$env_file" && -f "$compose_file" ]] || {
  printf 'Cockpit production configuration is missing or unsafe.\n' >&2
  exit 1
}

env_value() {
  local wanted="$1" line
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "${line%%=*}" != "$wanted" ]] || { printf '%s' "${line#*=}"; return 0; }
  done < "$env_file"
}

environment_id="$(env_value COCKPIT_MONITORING_ENVIRONMENT_ID)"
uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
[[ "$environment_id" =~ $uuid_pattern ]] || {
  printf 'Canonical Cockpit monitoring environment UUID ontbreekt of is ongeldig.\n' >&2
  exit 1
}

if [[ -e "$bundle" ]]; then
  [[ -f "$bundle" && ! -L "$bundle" && "$(stat -c '%a:%u' "$bundle")" == 600:0 ]] || {
    printf 'Bestaande observer provisioningbundle is niet root-owned mode 0600.\n' >&2
    exit 1
  }
  mapfile -t lines < "$bundle"
  [[ ${#lines[@]} == 3 && "${lines[0]}" == "COCKPIT_ENVIRONMENT_ID=$environment_id" &&
     "${lines[1]}" == PLENORA_OBSERVER_ID=* && "${lines[2]}" == PLENORA_OBSERVER_TOKEN=* ]] || {
    printf 'Bestaande observer provisioningbundle is ongeldig.\n' >&2
    exit 1
  }
  observer_id="${lines[1]#PLENORA_OBSERVER_ID=}"
  observer_token="${lines[2]#PLENORA_OBSERVER_TOKEN=}"
else
  [[ -z "$(env_value PLENORA_OBSERVER_ID)" && -z "$(env_value PLENORA_OBSERVER_TOKEN)" ]] || {
    printf 'Observer identity bestaat al; automatische reprovisioning is geweigerd.\n' >&2
    exit 1
  }
  raw="$(openssl rand -hex 16)"
  observer_id="${raw:0:8}-${raw:8:4}-4${raw:13:3}-8${raw:17:3}-${raw:20:12}"
  observer_token="$(openssl rand -hex 32)"
  [[ "$observer_id" =~ $uuid_pattern && "$observer_token" =~ ^[0-9a-f]{64}$ ]] || {
    printf 'Veilige observer identity-generatie is mislukt.\n' >&2
    exit 1
  }
  temporary="$(mktemp "$repo_root/.observer-identity.provision.tmp.XXXXXX")"
  printf 'COCKPIT_ENVIRONMENT_ID=%s\nPLENORA_OBSERVER_ID=%s\nPLENORA_OBSERVER_TOKEN=%s\n' \
    "$environment_id" "$observer_id" "$observer_token" > "$temporary"
  chmod 600 "$temporary"
  mv -- "$temporary" "$bundle"
  temporary=""
  chmod 600 "$bundle"
fi

compose=(docker compose --env-file "$env_file" -f "$compose_file")
[[ -n "$("${compose[@]}" ps --status running -q cockpit-backend)" ]] || {
  printf 'Cockpit backend is niet actief.\n' >&2
  exit 1
}
export COCKPIT_MONITORING_OBSERVER_ID="$observer_id"
export COCKPIT_MONITORING_OBSERVER_SECRET="$observer_token"
"${compose[@]}" exec -T \
  -e COCKPIT_MONITORING_OBSERVER_ID -e COCKPIT_MONITORING_OBSERVER_SECRET \
  cockpit-backend python -m app.cli seed-monitoring >/dev/null

export COCKPIT_ROTATION_ENVIRONMENT_ID="$environment_id"
export COCKPIT_ROTATION_COLLECTOR_ID="$observer_id"
export COCKPIT_ROTATION_CANDIDATE_SECRET="$observer_token"
"${compose[@]}" exec -T \
  -e COCKPIT_ROTATION_ENVIRONMENT_ID -e COCKPIT_ROTATION_COLLECTOR_ID \
  -e COCKPIT_ROTATION_CANDIDATE_SECRET \
  cockpit-backend python -m app.cli verify-collector-secret >/dev/null

temporary="$(mktemp "$repo_root/.env.deploy.tmp.XXXXXX")"
found_id=false
found_token=false
while IFS= read -r line || [[ -n "$line" ]]; do
  case "${line%%=*}" in
    PLENORA_OBSERVER_ID) printf 'PLENORA_OBSERVER_ID=%s\n' "$observer_id"; found_id=true ;;
    PLENORA_OBSERVER_TOKEN) printf 'PLENORA_OBSERVER_TOKEN=%s\n' "$observer_token"; found_token=true ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$env_file" > "$temporary"
[[ "$found_id" == true && "$found_token" == true ]] || {
  printf 'Observer keys ontbreken in .env.deploy.\n' >&2
  exit 1
}
chmod 600 "$temporary"
docker compose --env-file "$temporary" -f "$compose_file" config --quiet
mv -- "$temporary" "$env_file"
temporary=""
chmod 600 "$env_file"
unset COCKPIT_MONITORING_OBSERVER_ID COCKPIT_MONITORING_OBSERVER_SECRET
unset COCKPIT_ROTATION_ENVIRONMENT_ID COCKPIT_ROTATION_COLLECTOR_ID
unset COCKPIT_ROTATION_CANDIDATE_SECRET
printf 'Observer identity veilig geprovisioned; private bundle gereed voor overdracht.\n'
