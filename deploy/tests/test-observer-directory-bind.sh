#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_root="$(mktemp -d)"
boundary="$test_root/boundary"
image="plenora-observer-directory-bind-test:local"
container="plenora-observer-directory-bind-test-$$"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker image rm -f "$image" >/dev/null 2>&1 || true
  rm -rf "$test_root"
}
trap cleanup EXIT

mkdir "$boundary"
printf '%s\n' '{"version":"A"}' > "$boundary/host.json"
printf '%s\n' '{"version":"A"}' > "$boundary/backup-status.json"
printf '%s\n' '{"version":"A"}' > "$boundary/offsite-status.json"
chmod 0755 "$boundary"
chmod 0644 "$boundary/host.json" "$boundary/backup-status.json" "$boundary/offsite-status.json"

docker build --quiet -f "$repo_root/observer/Dockerfile" \
  --target production -t "$image" "$repo_root" >/dev/null
docker run -d --name "$container" \
  --user 10003:10003 --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount "type=bind,src=$boundary,dst=/status,readonly" \
  "$image" python -c 'import time; time.sleep(300)' >/dev/null

for name in host.json backup-status.json offsite-status.json; do
  [[ "$(docker exec "$container" python -c \
    "from pathlib import Path; print(Path('/status/$name').read_text().strip())")" == \
    '{"version":"A"}' ]]
done

BOUNDARY_TEST_DIR="$boundary" python3 - <<'PY'
import os
from pathlib import Path

directory = Path(os.environ["BOUNDARY_TEST_DIR"])
for name in ("host.json", "backup-status.json", "offsite-status.json"):
    temporary = directory / f".{name}.tmp"
    temporary.write_text('{"version":"B"}\n')
    os.chmod(temporary, 0o644)
    os.replace(temporary, directory / name)
PY

for name in host.json backup-status.json offsite-status.json; do
  [[ "$(docker exec "$container" python -c \
    "from pathlib import Path; print(Path('/status/$name').read_text().strip())")" == \
    '{"version":"B"}' ]]
done

[[ "$(docker inspect -f \
  '{{range .Mounts}}{{if eq .Destination "/status"}}{{.Type}}:{{.RW}}{{end}}{{end}}' \
  "$container")" == 'bind:false' ]]

if docker exec "$container" python -c \
  'from pathlib import Path; Path("/status/forbidden").write_text("no")' >/dev/null 2>&1; then
  printf 'non-root observer unexpectedly wrote to /status\n' >&2
  exit 1
fi

[[ "$(docker exec "$container" python -c \
  'from pathlib import Path; print("\n".join(sorted(p.name for p in Path("/status").iterdir())))')" == \
  $'backup-status.json\nhost.json\noffsite-status.json' ]]

grep -Fqx '      - /run/plenora-cockpit:/status:ro' \
  "$repo_root/docker-compose.observer.yml"
if grep -Fq '/var/backups' "$repo_root/docker-compose.observer.yml"; then
  printf 'observer compose unexpectedly mounts /var/backups\n' >&2
  exit 1
fi
PLENORA_OBSERVER_TOKEN=test-token \
PLENORA_OBSERVER_RELEASE=test-release \
PLENORA_MONITOR_DATABASE_URL=postgresql://monitor:test@database:5432/plenora \
DOCKER_GID=999 \
OBSERVER_CONTAINER_CADDY=test-caddy \
OBSERVER_CONTAINER_FRONTEND=test-frontend \
OBSERVER_CONTAINER_BACKEND=test-backend \
OBSERVER_CONTAINER_DB=test-database \
OBSERVER_CONTAINER_MAIL_WORKER=test-mail-worker \
docker compose --env-file "$repo_root/.env.observer.example" \
  -f "$repo_root/docker-compose.observer.yml" config --quiet

printf 'observer directory-bind atomic replacement test passed\n'
