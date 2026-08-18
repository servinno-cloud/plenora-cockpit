#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
test_root="$(mktemp -d)"
cleanup() { rm -rf -- "$test_root"; }
trap cleanup EXIT HUP INT TERM

mkdir -p "$test_root/deploy" "$test_root/bin"
cp "$source_root/deploy/init-env.sh" "$test_root/deploy/init-env.sh"
cp "$source_root/.env.deploy.example" "$test_root/.env.deploy.example"
cp "$source_root/docker-compose.deploy.yml" "$test_root/docker-compose.deploy.yml"
cat > "$test_root/bin/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '0123456789abcdef0123456789abcdef01234567'
EOF
chmod 700 "$test_root/bin/git"
export PATH="$test_root/bin:$PATH"

output="$(bash "$test_root/deploy/init-env.sh")"
[[ "$output" == 'Cockpit production environment initialized successfully.' ]]
docker compose --env-file "$test_root/.env.deploy" \
  -f "$test_root/docker-compose.deploy.yml" config --quiet
printf 'init-env Compose validation passed\n'
