#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM

[[ "$EUID" -eq 0 ]] || { printf 'test requires root, matching production helper\n'; exit 77; }
mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/configure-notifications.sh" "$test_root/deploy/"
cp "$source_root/docker-compose.deploy.yml" "$test_root/"

cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${NOTIFICATION_TEST_ARGV:?}"
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
notification = {key: value for key, value in values.items() if key.startswith("COCKPIT_NOTIFICATION_")}
print(json.dumps({"services": {
    "cockpit-notification-worker": {"environment": notification},
    "cockpit-backend": {"environment": {
        key: value for key, value in notification.items()
        if key in {"COCKPIT_NOTIFICATION_EMAIL_TO", "COCKPIT_NOTIFICATION_EMAIL_FROM",
                   "COCKPIT_NOTIFICATION_SMTP_HOST"}
    }},
    "cockpit-frontend": {"environment": {}},
    "cockpit-collector": {"environment": {}},
}}))
PY
fi
EOF
chmod 700 "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"
export NOTIFICATION_TEST_ARGV="$test_root/docker.argv"

write_base_env() {
  cat > "$test_root/.env.deploy" <<'EOF'
COCKPIT_PUBLIC_URL=https://cockpit.plenora.nl
COCKPIT_SECRET_KEY=existing-non-notification-secret-value
POSTGRES_DB=plenora_cockpit
COCKPIT_NOTIFICATION_EMAIL_TO=
COCKPIT_NOTIFICATION_EMAIL_FROM=
COCKPIT_NOTIFICATION_SMTP_HOST=
COCKPIT_NOTIFICATION_SMTP_PORT=587
COCKPIT_NOTIFICATION_SMTP_USERNAME=
COCKPIT_NOTIFICATION_SMTP_PASSWORD=
COCKPIT_NOTIFICATION_SMTP_STARTTLS=true
CUSTOM_UNRELATED_VALUE=keep=this exactly
EOF
  chmod 600 "$test_root/.env.deploy"
}

api_key='re_abcdefghijklmnopqrstuvwxyz0123456789'
write_base_env
output="$test_root/output"
error="$test_root/error"
if ! printf 'ops@example.nl\n\n%s\n' "$api_key" |
  bash "$test_root/deploy/configure-notifications.sh" >"$output" 2>"$error"; then
  if grep -Fq "$api_key" "$output" "$error"; then
    printf 'helper failed and exposed the test key\n' >&2
  else
    sed 's/^/helper: /' "$error" >&2
  fi
  exit 1
fi
grep -Fxq 'COCKPIT_NOTIFICATION_EMAIL_TO=ops@example.nl' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_NOTIFICATION_EMAIL_FROM=Cockpit <cockpit@notify.plenora.nl>' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_NOTIFICATION_SMTP_HOST=smtp.resend.com' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_NOTIFICATION_SMTP_PORT=587' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_NOTIFICATION_SMTP_USERNAME=resend' "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_NOTIFICATION_SMTP_STARTTLS=true' "$test_root/.env.deploy"
grep -Fxq 'CUSTOM_UNRELATED_VALUE=keep=this exactly' "$test_root/.env.deploy"
[[ "$(stat -c '%a' "$test_root/.env.deploy")" == 600 ]]
! grep -Fq "$api_key" "$output" "$error" "$NOTIFICATION_TEST_ARGV"
[[ -z "$(find "$test_root" -maxdepth 1 -name '.notification-*' -print -quit)" ]]

before="$(sha256sum "$test_root/.env.deploy")"
if printf 'ignored@example.nl\n\n%s\n' "$api_key" |
  bash "$test_root/deploy/configure-notifications.sh" >"$output" 2>"$error"; then
  printf 'existing notification configuration was overwritten without --force\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$before" ]]

custom_from='Plenora Cockpit <alerts@notify.plenora.nl>'
printf 'new@example.nl\n%s\n%s\n' "$custom_from" "$api_key" |
  bash "$test_root/deploy/configure-notifications.sh" --force >"$output" 2>"$error"
grep -Fxq "COCKPIT_NOTIFICATION_EMAIL_FROM=$custom_from" "$test_root/.env.deploy"
grep -Fxq 'COCKPIT_NOTIFICATION_EMAIL_TO=new@example.nl' "$test_root/.env.deploy"
! grep -Fq "$api_key" "$output" "$error" "$NOTIFICATION_TEST_ARGV"

write_base_env
before="$(sha256sum "$test_root/.env.deploy")"
if printf 'invalid-address\n\n%s\n' "$api_key" |
  bash "$test_root/deploy/configure-notifications.sh" >"$output" 2>"$error"; then
  printf 'invalid recipient was accepted\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$before" ]]

if printf 'ops@example.nl\n\n\n' |
  bash "$test_root/deploy/configure-notifications.sh" >"$output" 2>"$error"; then
  printf 'empty Resend key was accepted\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$before" ]]

grep -Fq 'cockpit-notification-worker' "$source_root/docker-compose.deploy.yml"
! sed -n '/^  cockpit-backend:/,/^  cockpit-frontend:/p' "$source_root/docker-compose.deploy.yml" |
  grep -Fq 'COCKPIT_NOTIFICATION_SMTP_PASSWORD'
! sed -n '/^  cockpit-frontend:/,/^  cockpit-notification-worker:/p' "$source_root/docker-compose.deploy.yml" |
  grep -Fq 'COCKPIT_NOTIFICATION_SMTP_PASSWORD'
! sed -n '/^  cockpit-collector:/,/^networks:/p' "$source_root/docker-compose.deploy.yml" |
  grep -Fq 'COCKPIT_NOTIFICATION_SMTP_PASSWORD'

printf 'notification configuration tests passed\n'
