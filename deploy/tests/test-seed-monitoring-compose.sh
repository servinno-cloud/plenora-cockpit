#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/../.." && pwd -P)"
compose=(docker compose --env-file "$repo_root/.env.deploy" -f "$repo_root/docker-compose.deploy.yml")

"${compose[@]}" config --quiet
"${compose[@]}" exec -T cockpit-backend python -m app.cli seed-monitoring
"${compose[@]}" exec -T cockpit-backend python -m app.cli seed-monitoring

printf 'production Compose monitoring seed passed twice idempotently\n'
