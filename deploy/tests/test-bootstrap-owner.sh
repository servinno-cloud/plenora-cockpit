#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM

mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/bootstrap-owner.sh" "$test_root/deploy/bootstrap-owner.sh"
printf '%s\n' 'POSTGRES_PASSWORD=unchanged-test-value' > "$test_root/.env.deploy"
chmod 600 "$test_root/.env.deploy"
cp "$source_root/docker-compose.deploy.yml" "$test_root/docker-compose.deploy.yml"

cat > "$test_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *'ps --status running --services'* ]]; then
  printf '%s\n' 'cockpit-backend'
  exit 0
fi
if [[ "$*" == *'exec -T'*'python -m app.cli create-owner'* ]]; then
  [[ -n "${COCKPIT_BOOTSTRAP_EMAIL:-}" ]]
  [[ -n "${COCKPIT_BOOTSTRAP_PASSWORD:-}" ]]
  [[ "$*" != *"$COCKPIT_BOOTSTRAP_PASSWORD"* ]]
  if [[ "${BOOTSTRAP_EXISTING:-false}" == true ]]; then
    printf '%s\n' 'An operator already exists; bootstrap refused' >&2
    exit 1
  fi
  printf '%s\n' 'OWNER created'
  exit 0
fi
exit 2
EOF
chmod 700 "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"

env_before="$(sha256sum "$test_root/.env.deploy")"
secret='A-safe-owner-password-2026!'
output="$(printf 'owner@example.com\n%s\n%s\n' "$secret" "$secret" | \
  bash "$test_root/deploy/bootstrap-owner.sh" 2>&1)"
[[ "$output" == *'OWNER succesvol aangemaakt.'* ]]
[[ "$output" != *"$secret"* ]]
[[ "$(sha256sum "$test_root/.env.deploy")" == "$env_before" ]]

if printf 'invalid-email\n%s\n%s\n' "$secret" "$secret" | \
  bash "$test_root/deploy/bootstrap-owner.sh" >/dev/null 2>&1; then
  printf 'invalid email was accepted\n' >&2
  exit 1
fi
if printf 'owner@example.com\n\n\n' | \
  bash "$test_root/deploy/bootstrap-owner.sh" >/dev/null 2>&1; then
  printf 'empty password was accepted\n' >&2
  exit 1
fi
if printf 'owner@example.com\ntoo-short\ntoo-short\n' | \
  bash "$test_root/deploy/bootstrap-owner.sh" >/dev/null 2>&1; then
  printf 'short password was accepted\n' >&2
  exit 1
fi
if printf 'owner@example.com\n%s\n%s\n' "$secret" 'different-password-2026!' | \
  bash "$test_root/deploy/bootstrap-owner.sh" >/dev/null 2>&1; then
  printf 'password mismatch was accepted\n' >&2
  exit 1
fi
if BOOTSTRAP_EXISTING=true printf 'owner@example.com\n%s\n%s\n' "$secret" "$secret" | \
  BOOTSTRAP_EXISTING=true bash "$test_root/deploy/bootstrap-owner.sh" >/dev/null 2>&1; then
  printf 'existing owner was accepted\n' >&2
  exit 1
fi
[[ "$(sha256sum "$test_root/.env.deploy")" == "$env_before" ]]

printf 'bootstrap-owner tests passed\n'
