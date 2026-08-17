import hashlib
import hmac
import http.client
import json
import os
import socket
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

MAX_RESPONSE = 32_768
FIXTURES = Path("/fixtures")
HOST_STATUS = Path(os.getenv("OBSERVER_HOST_STATUS_PATH", "/status/host.json"))
ALLOWED_SERVICES = {
    "caddy": os.getenv("OBSERVER_CONTAINER_CADDY", "plenora-caddy"),
    "frontend": os.getenv("OBSERVER_CONTAINER_FRONTEND", "plenora-frontend"),
    "backend": os.getenv("OBSERVER_CONTAINER_BACKEND", "plenora-backend"),
    "db": os.getenv("OBSERVER_CONTAINER_DB", "plenora-db"),
    "mail-worker": os.getenv("OBSERVER_CONTAINER_MAIL_WORKER", "plenora-mail-worker"),
}
attempts: dict[str, deque[float]] = defaultdict(deque)


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost", timeout=3)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def authorized(header: str | None) -> bool:
    token = os.getenv("OBSERVER_TOKEN", "")
    supplied = (header or "").removeprefix("Bearer ")
    return bool(token) and len(token) >= 32 and hmac.compare_digest(token, supplied)


def limited(client: str) -> bool:
    now = time.monotonic()
    bucket = attempts[client]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= 120:
        return True
    bucket.append(now)
    return False


def docker_inspect(container: str) -> dict:
    connection = UnixConnection("/var/run/docker.sock")
    connection.request("GET", f"/v1.41/containers/{quote(container, safe='')}/json")
    response = connection.getresponse()
    if response.status != 200:
        raise LookupError(container)
    raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Docker response too large")
    return json.loads(raw)


def safe_image_identifier(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:16]


def live_services() -> dict:
    services = []
    for key, container in ALLOWED_SERVICES.items():
        item = docker_inspect(container)
        state = item.get("State", {})
        health = state.get("Health", {}).get("Status", "none")
        if health not in {"healthy", "unhealthy", "starting", "none"}:
            health = "none"
        services.append({
                "service_key": key,
            "running": state.get("Running") is True,
            "health": health,
            "restart_count": int(item.get("RestartCount", 0)),
            "started_at": str(state.get("StartedAt", ""))[:40],
            "image_identifier": safe_image_identifier(str(item.get("Image", "missing"))),
        })
    return {"services": services}


def read_closed_json(path: Path, keys: set[str]) -> dict:
    raw = path.read_bytes()
    if len(raw) > MAX_RESPONSE:
        raise ValueError("status response too large")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("status contract mismatch")
    return value


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, value: dict):
        payload = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "healthy"})
            return
        if limited(self.client_address[0]):
            self.send_error(429)
            return
        if not authorized(self.headers.get("Authorization")):
            self.send_error(401)
            return
        mode = os.getenv("OBSERVER_MODE", "production")
        try:
            if mode == "fixture":
                routes = {
                    "/v1/database": "database.json",
                    "/v1/mail": "mail.json",
                    "/v1/services": "services.json",
                }
                filename = routes.get(self.path)
                if not filename:
                    self.send_error(404)
                    return
                self.send_json(200, json.loads((FIXTURES / filename).read_bytes()))
            elif self.path == "/v1/services":
                self.send_json(200, live_services())
            elif self.path == "/v1/host":
                keys = {
                    "timestamp", "uptime_seconds", "root_total_bytes", "root_used_bytes",
                    "root_free_bytes", "root_inode_used_percent", "backup_total_bytes",
                    "backup_used_bytes", "backup_free_bytes", "backup_inode_used_percent",
                    "load_1m", "load_5m", "load_15m",
                }
                self.send_json(200, read_closed_json(HOST_STATUS, keys))
            else:
                self.send_error(404)
        except (OSError, ValueError, LookupError, json.JSONDecodeError):
            self.send_error(503)

    def do_POST(self):
        self.send_error(405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    mode = os.getenv("OBSERVER_MODE", "production")
    if mode not in {"fixture", "production"}:
        raise SystemExit("OBSERVER_MODE must be fixture or production")
    if mode == "production" and FIXTURES.exists():
        raise SystemExit("fixture mount forbidden in production")
    if len(os.getenv("OBSERVER_TOKEN", "")) < 32:
        raise SystemExit("OBSERVER_TOKEN must contain at least 32 characters")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
