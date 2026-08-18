#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/plenora-observer/app
compose=(docker compose --env-file .env.observer -f docker-compose.observer.yml)
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d
"${compose[@]}" ps
