#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
env_file="$repo_root/.env.deploy"
compose_file="$repo_root/docker-compose.deploy.yml"
mode=configure
force=false
temporary=""
validation_log=""
validation_json=""
api_key=""

cleanup() {
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  [[ -z "$validation_log" ]] || rm -f -- "$validation_log"
  [[ -z "$validation_json" ]] || rm -f -- "$validation_json"
  unset api_key
}
trap cleanup EXIT HUP INT TERM

usage() {
  printf 'Usage: sudo bash deploy/configure-analysis.sh [--force|--enable]\n'
}
case "${1:-}" in
  "") ;;
  --force) force=true ;;
  --enable) mode=enable ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
(( $# <= 1 )) || { usage >&2; exit 2; }

[[ "$EUID" -eq 0 ]] || { printf 'This helper must run as root.\n' >&2; exit 1; }
for command in docker python3 mktemp chmod mv stat; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done
[[ -f "$env_file" && ! -L "$env_file" ]] || {
  printf '.env.deploy must exist as a regular non-symlink file.\n' >&2
  exit 1
}
[[ "$(stat -c '%a' -- "$env_file")" == 600 ]] || {
  printf '.env.deploy must have mode 0600.\n' >&2
  exit 1
}
[[ "$(stat -c '%u' -- "$env_file")" == 0 ]] || {
  printf '.env.deploy must be owned by root.\n' >&2
  exit 1
}
[[ -f "$compose_file" && ! -L "$compose_file" ]] || {
  printf 'docker-compose.deploy.yml is missing or unsafe.\n' >&2
  exit 1
}

analysis_exists=false
stored_key=false
while IFS= read -r line || [[ -n "$line" ]]; do
  case "${line%%=*}" in
    COCKPIT_ANALYSIS_API_KEY)
      if [[ -n "${line#*=}" ]]; then
        analysis_exists=true
        stored_key=true
      fi
      ;;
  esac
done < "$env_file"

if [[ "$mode" == enable ]]; then
  [[ "$stored_key" == true ]] || {
    printf 'Analysis configuration is incomplete; configure it first.\n' >&2
    exit 1
  }
elif [[ "$analysis_exists" == true && "$force" != true ]]; then
  printf 'Analysis configuration already exists; use --force explicitly.\n' >&2
  exit 1
else
  read -r -s -p 'OpenAI API key: ' api_key
  printf '\n' >&2
  [[ "$api_key" =~ ^sk-[A-Za-z0-9_-]{20,}$ ]] || {
    printf 'OpenAI API key heeft geen plausibel formaat.\n' >&2
    exit 1
  }
fi

temporary="$(mktemp "$repo_root/.env.deploy.analysis.XXXXXX")"
validation_log="$(mktemp "$repo_root/.analysis-validation.XXXXXX")"
validation_json="$(mktemp "$repo_root/.analysis-config.XXXXXX")"
chmod 600 "$temporary" "$validation_log" "$validation_json"

declare -A written=()
while IFS= read -r line || [[ -n "$line" ]]; do
  key="${line%%=*}"
  case "$key" in
    COCKPIT_ANALYSIS_ENABLED)
      [[ "$mode" == enable ]] && value=true || value=false
      printf '%s=%s\n' "$key" "$value"; written[$key]=1 ;;
    COCKPIT_ANALYSIS_PROVIDER) printf '%s\n' 'COCKPIT_ANALYSIS_PROVIDER=openai'; written[$key]=1 ;;
    COCKPIT_ANALYSIS_MODEL) printf '%s\n' 'COCKPIT_ANALYSIS_MODEL=gpt-5.6-terra'; written[$key]=1 ;;
    COCKPIT_ANALYSIS_API_KEY)
      if [[ "$mode" == enable ]]; then printf '%s\n' "$line"; else printf '%s=%s\n' "$key" "$api_key"; fi
      written[$key]=1 ;;
    COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS) printf '%s\n' 'COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS=800'; written[$key]=1 ;;
    COCKPIT_ANALYSIS_TIMEOUT_SECONDS) printf '%s\n' 'COCKPIT_ANALYSIS_TIMEOUT_SECONDS=20'; written[$key]=1 ;;
    COCKPIT_ANALYSIS_MAX_ATTEMPTS) printf '%s\n' 'COCKPIT_ANALYSIS_MAX_ATTEMPTS=2'; written[$key]=1 ;;
    COCKPIT_ANALYSIS_MAX_OBSERVATIONS) printf '%s\n' 'COCKPIT_ANALYSIS_MAX_OBSERVATIONS=25'; written[$key]=1 ;;
    COCKPIT_ANALYSIS_MAX_HISTORY) printf '%s\n' 'COCKPIT_ANALYSIS_MAX_HISTORY=5'; written[$key]=1 ;;
    COCKPIT_AI_MONTHLY_BUDGET_EUR) printf '%s\n' 'COCKPIT_AI_MONTHLY_BUDGET_EUR=100'; written[$key]=1 ;;
    COCKPIT_AI_USD_TO_EUR_RATE) printf '%s\n' 'COCKPIT_AI_USD_TO_EUR_RATE=1.00'; written[$key]=1 ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$env_file" > "$temporary"

for key in COCKPIT_ANALYSIS_ENABLED COCKPIT_ANALYSIS_PROVIDER COCKPIT_ANALYSIS_MODEL \
  COCKPIT_ANALYSIS_API_KEY COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS \
  COCKPIT_ANALYSIS_TIMEOUT_SECONDS COCKPIT_ANALYSIS_MAX_ATTEMPTS \
  COCKPIT_ANALYSIS_MAX_OBSERVATIONS COCKPIT_ANALYSIS_MAX_HISTORY \
  COCKPIT_AI_MONTHLY_BUDGET_EUR COCKPIT_AI_USD_TO_EUR_RATE; do
  [[ -n "${written[$key]:-}" ]] && continue
  case "$key" in
    COCKPIT_ANALYSIS_ENABLED) [[ "$mode" == enable ]] && value=true || value=false ;;
    COCKPIT_ANALYSIS_PROVIDER) value=openai ;;
    COCKPIT_ANALYSIS_MODEL) value=gpt-5.6-terra ;;
    COCKPIT_ANALYSIS_API_KEY) value="$api_key" ;;
    COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS) value=800 ;;
    COCKPIT_ANALYSIS_TIMEOUT_SECONDS) value=20 ;;
    COCKPIT_ANALYSIS_MAX_ATTEMPTS) value=2 ;;
    COCKPIT_ANALYSIS_MAX_OBSERVATIONS) value=25 ;;
    COCKPIT_ANALYSIS_MAX_HISTORY) value=5 ;;
    COCKPIT_AI_MONTHLY_BUDGET_EUR) value=100 ;;
    COCKPIT_AI_USD_TO_EUR_RATE) value=1.00 ;;
  esac
  printf '%s=%s\n' "$key" "$value" >> "$temporary"
done
chmod 600 "$temporary"

if ! docker compose --env-file "$temporary" -f "$compose_file" config --quiet \
  >"$validation_log" 2>&1; then
  printf 'Analysis configuration failed Compose validation.\n' >&2
  exit 1
fi
if ! docker compose --env-file "$temporary" -f "$compose_file" config --format json \
  >"$validation_json" 2>"$validation_log"; then
  printf 'Analysis configuration could not be inspected safely.\n' >&2
  exit 1
fi
python3 - "$validation_json" "$mode" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    services = json.load(handle)["services"]
worker = services["cockpit-analysis-worker"]
environment = worker.get("environment", {})
expected = {
    "COCKPIT_ANALYSIS_ENABLED": "true" if sys.argv[2] == "enable" else "false",
    "COCKPIT_ANALYSIS_PROVIDER": "openai",
    "COCKPIT_ANALYSIS_MODEL": "gpt-5.6-terra",
    "COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS": "800",
    "COCKPIT_ANALYSIS_TIMEOUT_SECONDS": "20",
    "COCKPIT_ANALYSIS_MAX_ATTEMPTS": "2",
    "COCKPIT_ANALYSIS_MAX_OBSERVATIONS": "25",
    "COCKPIT_ANALYSIS_MAX_HISTORY": "5",
    "COCKPIT_AI_MONTHLY_BUDGET_EUR": "100",
    "COCKPIT_AI_USD_TO_EUR_RATE": "1.00",
}
if any(str(environment.get(key, "")).lower() != value for key, value in expected.items()):
    raise SystemExit(1)
if not environment.get("COCKPIT_ANALYSIS_API_KEY"):
    raise SystemExit(1)
if str(worker.get("user")) != "10001:10001":
    raise SystemExit(1)
if worker.get("read_only") is not True or worker.get("ports") or worker.get("volumes"):
    raise SystemExit(1)
if "ALL" not in worker.get("cap_drop", []):
    raise SystemExit(1)
if "no-new-privileges:true" not in worker.get("security_opt", []):
    raise SystemExit(1)
if set(worker.get("networks", {})) != {"cockpit-internal", "analysis-egress"}:
    raise SystemExit(1)
for key in environment:
    if "SMTP" in key or key.startswith("PLENORA_") or "DOCKER" in key:
        raise SystemExit(1)
for name, service in services.items():
    if name != "cockpit-analysis-worker" and "COCKPIT_ANALYSIS_API_KEY" in service.get(
        "environment", {}
    ):
        raise SystemExit(1)
PY

mv -f -- "$temporary" "$env_file"
temporary=""
chmod 600 "$env_file"
if [[ "$mode" == enable ]]; then
  printf 'Cockpit Operations Analyst is expliciet ingeschakeld.\n'
else
  printf 'Cockpit Operations Analyst is veilig geconfigureerd en blijft uitgeschakeld.\n'
fi
