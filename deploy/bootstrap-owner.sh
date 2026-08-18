#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
set +o history 2>/dev/null || true

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
env_file="$repo_root/.env.deploy"
compose_file="$repo_root/docker-compose.deploy.yml"
email=""
password=""
password_confirmation=""
bootstrap_output=""

cleanup() {
  unset email password password_confirmation bootstrap_output
  unset COCKPIT_BOOTSTRAP_EMAIL COCKPIT_BOOTSTRAP_PASSWORD
}
trap cleanup EXIT HUP INT TERM

for command in docker sha256sum; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  fi
done
if [[ ! -r "$env_file" || ! -f "$compose_file" ]]; then
  printf '.env.deploy or docker-compose.deploy.yml is missing.\n' >&2
  exit 1
fi

compose=(docker compose --env-file "$env_file" -f "$compose_file")
running_services="$("${compose[@]}" ps --status running --services)"
if ! grep -Fxq 'cockpit-backend' <<< "$running_services"; then
  printf 'cockpit-backend is not running.\n' >&2
  exit 1
fi

IFS= read -r -p 'OWNER e-mailadres: ' email
if [[ ! "$email" =~ ^[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}$ ]]; then
  printf 'Ongeldig OWNER e-mailadres.\n' >&2
  exit 1
fi

IFS= read -r -s -p 'OWNER wachtwoord: ' password
printf '\n' >&2
if [[ -z "$password" || ${#password} -lt 14 ]]; then
  printf 'Het OWNER wachtwoord moet minimaal 14 tekens bevatten.\n' >&2
  exit 1
fi
IFS= read -r -s -p 'Herhaal wachtwoord: ' password_confirmation
printf '\n' >&2
if [[ "$password" != "$password_confirmation" ]]; then
  printf 'De wachtwoorden komen niet overeen.\n' >&2
  exit 1
fi

env_hash_before="$(sha256sum "$env_file")"
export COCKPIT_BOOTSTRAP_EMAIL="$email"
export COCKPIT_BOOTSTRAP_PASSWORD="$password"
password_confirmation=""

if ! bootstrap_output="$(
  "${compose[@]}" exec -T \
    -e COCKPIT_BOOTSTRAP_EMAIL \
    -e COCKPIT_BOOTSTRAP_PASSWORD \
    cockpit-backend python -m app.cli create-owner 2>&1
)"; then
  if [[ "$bootstrap_output" == *'bootstrap refused'* || "$bootstrap_output" == *'already exists'* ]]; then
    printf 'OWNER-bootstrap geweigerd: er bestaat al een operator.\n' >&2
  else
    printf 'OWNER kon niet worden aangemaakt.\n' >&2
  fi
  exit 1
fi

unset COCKPIT_BOOTSTRAP_EMAIL COCKPIT_BOOTSTRAP_PASSWORD
password=""
password_confirmation=""

env_hash_after="$(sha256sum "$env_file")"
if [[ "$env_hash_before" != "$env_hash_after" ]]; then
  printf 'Veiligheidscontrole mislukt: .env.deploy is gewijzigd.\n' >&2
  exit 1
fi

printf 'OWNER succesvol aangemaakt.\n'
