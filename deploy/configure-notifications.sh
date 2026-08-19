#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
env_file="$repo_root/.env.deploy"
compose_file="$repo_root/docker-compose.deploy.yml"
force=false
temporary=""
validation_log=""
validation_json=""
recipient=""
sender=""
sender_mailbox=""
api_key=""

cleanup() {
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  [[ -z "$validation_log" ]] || rm -f -- "$validation_log"
  [[ -z "$validation_json" ]] || rm -f -- "$validation_json"
  unset recipient sender sender_mailbox api_key
}
trap cleanup EXIT HUP INT TERM

usage() { printf 'Usage: sudo bash deploy/configure-notifications.sh [--force]\n'; }
case "${1:-}" in
  "") ;;
  --force) force=true ;;
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

notification_exists=false
while IFS= read -r line || [[ -n "$line" ]]; do
  case "${line%%=*}" in
    COCKPIT_NOTIFICATION_EMAIL_TO|COCKPIT_NOTIFICATION_EMAIL_FROM|\
    COCKPIT_NOTIFICATION_SMTP_HOST|COCKPIT_NOTIFICATION_SMTP_USERNAME|\
    COCKPIT_NOTIFICATION_SMTP_PASSWORD)
      [[ -z "${line#*=}" ]] || notification_exists=true
      ;;
  esac
done < "$env_file"
if [[ "$notification_exists" == true && "$force" != true ]]; then
  printf 'Notification configuration already exists; use --force explicitly.\n' >&2
  exit 1
fi

read -r -p 'Notification recipient e-mailadres: ' recipient
read -r -p 'Afzenderadres [Cockpit <cockpit@notify.plenora.nl>]: ' sender
sender="${sender:-Cockpit <cockpit@notify.plenora.nl>}"
read -r -s -p 'Resend API key: ' api_key
printf '\n' >&2

email_pattern='^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$'
[[ "$recipient" != *$'\n'* && "$recipient" != *$'\r'* && "$recipient" =~ $email_pattern ]] || {
  printf 'Recipient e-mailadres is ongeldig.\n' >&2
  exit 1
}
if [[ "$sender" =~ ^.+[[:space:]]\<[^\<\>]+\>$ ]]; then
  sender_mailbox="${sender##*<}"
  sender_mailbox="${sender_mailbox%>}"
else
  sender_mailbox="$sender"
fi
[[ "$sender" != *$'\n'* && "$sender" != *$'\r'* && "$sender_mailbox" =~ $email_pattern ]] || {
  printf 'Afzenderadres bevat geen geldig mailboxadres.\n' >&2
  exit 1
}
[[ "$api_key" =~ ^re_[A-Za-z0-9_-]{20,}$ ]] || {
  printf 'Resend API key heeft geen plausibel formaat.\n' >&2
  exit 1
}

temporary="$(mktemp "$repo_root/.env.deploy.notifications.XXXXXX")"
validation_log="$(mktemp "$repo_root/.notification-validation.XXXXXX")"
validation_json="$(mktemp "$repo_root/.notification-config.XXXXXX")"
chmod 600 "$temporary" "$validation_log" "$validation_json"

declare -A written=()
while IFS= read -r line || [[ -n "$line" ]]; do
  key="${line%%=*}"
  case "$key" in
    COCKPIT_NOTIFICATION_EMAIL_TO) printf 'COCKPIT_NOTIFICATION_EMAIL_TO=%s\n' "$recipient"; written[$key]=1 ;;
    COCKPIT_NOTIFICATION_EMAIL_FROM) printf 'COCKPIT_NOTIFICATION_EMAIL_FROM=%s\n' "$sender"; written[$key]=1 ;;
    COCKPIT_NOTIFICATION_SMTP_HOST) printf '%s\n' 'COCKPIT_NOTIFICATION_SMTP_HOST=smtp.resend.com'; written[$key]=1 ;;
    COCKPIT_NOTIFICATION_SMTP_PORT) printf '%s\n' 'COCKPIT_NOTIFICATION_SMTP_PORT=587'; written[$key]=1 ;;
    COCKPIT_NOTIFICATION_SMTP_USERNAME) printf '%s\n' 'COCKPIT_NOTIFICATION_SMTP_USERNAME=resend'; written[$key]=1 ;;
    COCKPIT_NOTIFICATION_SMTP_PASSWORD) printf 'COCKPIT_NOTIFICATION_SMTP_PASSWORD=%s\n' "$api_key"; written[$key]=1 ;;
    COCKPIT_NOTIFICATION_SMTP_STARTTLS) printf '%s\n' 'COCKPIT_NOTIFICATION_SMTP_STARTTLS=true'; written[$key]=1 ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$env_file" > "$temporary"
for key in COCKPIT_NOTIFICATION_EMAIL_TO COCKPIT_NOTIFICATION_EMAIL_FROM \
  COCKPIT_NOTIFICATION_SMTP_HOST COCKPIT_NOTIFICATION_SMTP_PORT \
  COCKPIT_NOTIFICATION_SMTP_USERNAME COCKPIT_NOTIFICATION_SMTP_PASSWORD \
  COCKPIT_NOTIFICATION_SMTP_STARTTLS; do
  [[ -n "${written[$key]:-}" ]] && continue
  case "$key" in
    COCKPIT_NOTIFICATION_EMAIL_TO) value="$recipient" ;;
    COCKPIT_NOTIFICATION_EMAIL_FROM) value="$sender" ;;
    COCKPIT_NOTIFICATION_SMTP_HOST) value="smtp.resend.com" ;;
    COCKPIT_NOTIFICATION_SMTP_PORT) value="587" ;;
    COCKPIT_NOTIFICATION_SMTP_USERNAME) value="resend" ;;
    COCKPIT_NOTIFICATION_SMTP_PASSWORD) value="$api_key" ;;
    COCKPIT_NOTIFICATION_SMTP_STARTTLS) value="true" ;;
  esac
  printf '%s=%s\n' "$key" "$value" >> "$temporary"
done
chmod 600 "$temporary"

if ! docker compose --env-file "$temporary" -f "$compose_file" config --quiet \
  >"$validation_log" 2>&1; then
  printf 'Notification configuration failed Compose validation.\n' >&2
  exit 1
fi
if ! docker compose --env-file "$temporary" -f "$compose_file" config --format json \
  >"$validation_json" 2>"$validation_log"; then
  printf 'Notification configuration could not be inspected safely.\n' >&2
  exit 1
fi
python3 - "$validation_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    services = json.load(handle)["services"]
worker = services["cockpit-notification-worker"].get("environment", {})
required = {
    "COCKPIT_NOTIFICATION_SMTP_HOST": "smtp.resend.com",
    "COCKPIT_NOTIFICATION_SMTP_PORT": "587",
    "COCKPIT_NOTIFICATION_SMTP_USERNAME": "resend",
    "COCKPIT_NOTIFICATION_SMTP_STARTTLS": "true",
}
if any(str(worker.get(key, "")).lower() != value for key, value in required.items()):
    raise SystemExit(1)
if not worker.get("COCKPIT_NOTIFICATION_EMAIL_TO") or not worker.get(
    "COCKPIT_NOTIFICATION_EMAIL_FROM"
) or not worker.get("COCKPIT_NOTIFICATION_SMTP_PASSWORD"):
    raise SystemExit(1)
for name in ("cockpit-backend", "cockpit-frontend", "cockpit-collector"):
    if "COCKPIT_NOTIFICATION_SMTP_PASSWORD" in services[name].get("environment", {}):
        raise SystemExit(1)
PY

mv -f -- "$temporary" "$env_file"
temporary=""
chmod 600 "$env_file"
printf 'Cockpit e-mailnotificaties zijn veilig geconfigureerd.\n'
