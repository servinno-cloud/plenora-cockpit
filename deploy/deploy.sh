#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/plenora-cockpit/app
set -a
source .env.deploy
set +a
export COCKPIT_MONITORING_ENVIRONMENT_ID="$COLLECTOR_ENVIRONMENT_ID"
export COCKPIT_MONITORING_COLLECTOR_ID="$COLLECTOR_ID"
export COCKPIT_MONITORING_COLLECTOR_SECRET="$COLLECTOR_TOKEN"
export COCKPIT_MONITORING_OBSERVER_ID="$PLENORA_OBSERVER_ID"
export COCKPIT_MONITORING_OBSERVER_SECRET="$PLENORA_OBSERVER_TOKEN"
compose=(docker compose --env-file .env.deploy -f docker-compose.deploy.yml)
"${compose[@]}" config --quiet
"${compose[@]}" build
"${compose[@]}" up -d cockpit-db
"${compose[@]}" exec -T cockpit-db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${compose[@]}" run --rm cockpit-backend alembic upgrade head
"${compose[@]}" run --rm \
  -e COCKPIT_MONITORING_ENVIRONMENT_ID \
  -e COCKPIT_MONITORING_COLLECTOR_ID \
  -e COCKPIT_MONITORING_COLLECTOR_SECRET \
  -e COCKPIT_MONITORING_OBSERVER_ID \
  -e COCKPIT_MONITORING_OBSERVER_SECRET \
  cockpit-backend python -m app.cli seed-monitoring
"${compose[@]}" up -d --remove-orphans
exec bash deploy/check.sh
