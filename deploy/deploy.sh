#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/plenora-cockpit/app
compose=(docker compose --env-file .env.deploy -f docker-compose.deploy.yml)
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d cockpit-db
"${compose[@]}" exec -T cockpit-db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${compose[@]}" run --rm cockpit-backend alembic upgrade head
"${compose[@]}" run --rm cockpit-backend python -m app.cli seed-monitoring
"${compose[@]}" up -d --remove-orphans
exec bash deploy/check.sh
