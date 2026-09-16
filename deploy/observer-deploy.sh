#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/plenora-observer/app
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || {
  printf 'Refusing to deploy a dirty worktree.\n' >&2
  exit 1
}
export DEPLOYMENT_RELEASE="$(git rev-parse --verify 'HEAD^{commit}')"
compose=(docker compose --env-file .env.observer -f docker-compose.observer.yml)
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d
"${compose[@]}" ps
