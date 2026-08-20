#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM

[[ "$EUID" -eq 0 ]] || { printf 'test requires root, matching production helper\n'; exit 77; }
mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/configure-analysis.sh" "$test_root/deploy/"
cp "$source_root/docker-compose.deploy.yml" "$test_root/"

cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${ANALYSIS_TEST_ARGV:?}"
env_file=""
format_json=false
while (( $# )); do
  case "$1" in
    --env-file) env_file="$2"; shift 2 ;;
    --format) [[ "$2" == json ]] && format_json=true; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$env_file" && -f "$env_file" ]] || exit 1
[[ "${ANALYSIS_TEST_FAIL_COMPOSE:-false}" != true ]] || exit 1
if [[ "$format_json" == true ]]; then
  python3 - "$env_file" <<'PY'
import json
import sys

values = {}
with open(sys.argv[1], encoding="utf-8") as handle:
    for raw in handle:
        key, separator, value = raw.rstrip("\n").partition("=")
        if separator:
            values[key] = value
analysis = {key: value for key, value in values.items()
            if key.startswith("COCKPIT_ANALYSIS_") or key.startswith("COCKPIT_AI_")}
print(json.dumps({"services": {
    "cockpit-analysis-worker": {
        "environment": analysis,
        "user": "10001:10001",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "networks": {"cockpit-internal": None, "analysis-egress": None},
    },
    "cockpit-backend": {"environment": {}},
    "cockpit-frontend": {"environment": {}},
    "cockpit-collector": {"environment": {}},
    "cockpit-notification-worker": {"environment": {}},
}}))
PY
fi
EOF
chmod 700 "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"
export ANALYSIS_TEST_ARGV="$test_root/docker.argv"

write_base_env() {
  cat > "$test_root/.env.deploy" <<'EOF'
COCKPIT_PUBLIC_URL=https://cockpit.plenora.nl
COCKPIT_SECRET_KEY=existing-secret
COCKPIT_ANALYSIS_ENABLED=false
COCKPIT_ANALYSIS_PROVIDER=openai
COCKPIT_ANALYSIS_MODEL=
COCKPIT_ANALYSIS_API_KEY=
COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS=800
COCKPIT_ANALYSIS_TIMEOUT_SECONDS=20
COCKPIT_ANALYSIS_MAX_ATTEMPTS=2
COCKPIT_ANALYSIS_MAX_OBSERVATIONS=25
COCKPIT_ANALYSIS_MAX_HISTORY=5
CUSTOM_UNRELATED_VALUE=keep=this exactly
EOF
  chmod 600 "$test_root/.env.deploy"
}

api_key='sk-proj-abcdefghijklmnopqrstuvwxyz0123456789'
output="$test_root/output"
error="$test_root/error"
write_base_env
printf '%s\n' "$api_key" |
  bash "$test_root/deploy/configure-analysis.sh" >"$output" 2>"$error"
grep -Fxq 'COCKPIT_ANALYSIS_ENABLED=false' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_ANALYSIS_PROVIDER=openai' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_ANALYSIS_MODEL=gpt-5.6-terra' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS=800' "$test_root/.env.deploy"
grep -Fxq 'CUSTOM_UNRELATED_VALUE=keep=this exactly' "$test_root/.env.deploy"
[[ "$(stat -c '%a' "$test_root/.env.deploy")" == 600 ]]
[[ "$(stat -c '%u' "$test_root/.env.deploy")" == 0 ]]
! grep -Fq "$api_key" "$output" "$error" "$ANALYSIS_TEST_ARGV"
[[ -z "$(find "$test_root" -maxdepth 1 -name '.analysis-*' -print -quit)" ]]

before="$(sha256sum "$test_root/.env.deploy")"
if printf '%s\n' "$api_key" |
  bash "$test_root/deploy/configure-analysis.sh" >"$output" 2>"$error"; then
  printf 'existing analysis configuration was overwritten without --force\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$before" ]]

bash "$test_root/deploy/configure-analysis.sh" --enable >"$output" 2>"$error"
grep -Fxq 'COCKPIT_ANALYSIS_ENABLED=true' "$test_root/.env.deploy"
! grep -Fq "$api_key" "$output" "$error" "$ANALYSIS_TEST_ARGV"

printf '%s\n' 'sk-proj-replacementabcdefghijklmnopqrstuvwxyz' |
  bash "$test_root/deploy/configure-analysis.sh" --force >"$output" 2>"$error"
grep -Fxq 'COCKPIT_ANALYSIS_ENABLED=false' "$test_root/.env.deploy"

write_base_env
before="$(sha256sum "$test_root/.env.deploy")"
if printf '\n' | bash "$test_root/deploy/configure-analysis.sh" >"$output" 2>"$error"; then
  printf 'empty OpenAI key was accepted\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$before" ]]

if printf '%s\n' "$api_key" | ANALYSIS_TEST_FAIL_COMPOSE=true \
  bash "$test_root/deploy/configure-analysis.sh" >"$output" 2>"$error"; then
  printf 'Compose failure was accepted\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$before" ]]
! grep -Fq "$api_key" "$output" "$error" "$ANALYSIS_TEST_ARGV"

for service in cockpit-backend cockpit-frontend cockpit-collector cockpit-notification-worker; do
  ! sed -n "/^  ${service}:/,/^  [a-z]/p" "$source_root/docker-compose.deploy.yml" |
    grep -Fq 'COCKPIT_ANALYSIS_API_KEY'
done

printf 'analysis configuration tests passed\n'
