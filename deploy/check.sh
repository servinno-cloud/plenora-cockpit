#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/plenora-cockpit/app
compose=(docker compose --env-file .env.deploy -f docker-compose.deploy.yml)
"${compose[@]}" config --quiet
"${compose[@]}" ps
"${compose[@]}" exec -T cockpit-backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"
"${compose[@]}" exec -T cockpit-frontend node -e "fetch('http://localhost:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
"${compose[@]}" exec -T cockpit-backend alembic current

