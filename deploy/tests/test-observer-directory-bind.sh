#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_root="$(mktemp -d)"
boundary="$test_root/boundary"
image="plenora-observer-directory-bind-test:local"
container="plenora-observer-directory-bind-test-$$"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$test_root"
}
trap cleanup EXIT

mkdir "$boundary"
printf '%s\n' '{"version":"A"}' > "$boundary/host.json"
printf '%s\n' '{"version":"A"}' > "$boundary/backup-status.json"
chmod 0755 "$boundary"
chmod 0644 "$boundary/host.json" "$boundary/backup-status.json"

docker build --quiet --target production -t "$image" "$repo_root" >/dev/null
docker run -d --name "$container" \
  --user 10003:10003 --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount "type=bind,src=$boundary,dst=/status,readonly" \
  "$image" python -c 'import time; time.sleep(300)' >/dev/null

for name in host.json backup-status.json; do
  [[ "$(docker exec "$container" python -c \
    "from pathlib import Path; print(Path('/status/$name').read_text().strip())")" == \
    '{"version":"A"}' ]]
done

BOUNDARY_TEST_DIR="$boundary" python - <<'PY'
import os
from pathlib import Path

directory = Path(os.environ["BOUNDARY_TEST_DIR"])
for name in ("host.json", "backup-status.json"):
    temporary = directory / f".{name}.tmp"
    temporary.write_text('{"version":"B"}\n')
    os.chmod(temporary, 0o644)
    os.replace(temporary, directory / name)
PY

for name in host.json backup-status.json; do
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
  $'backup-status.json\nhost.json' ]]

grep -Fqx '      - /run/plenora-cockpit:/status:ro' \
  "$repo_root/docker-compose.observer.yml"
! grep -Fq '/var/backups' "$repo_root/docker-compose.observer.yml"
docker compose --env-file "$repo_root/.env.observer.example" \
  -f "$repo_root/docker-compose.observer.yml" config --quiet

printf 'observer directory-bind atomic replacement test passed\n'
