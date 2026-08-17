import json
import os
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _obs(target: str, signal: str, source: str, value: Any, state="HEALTHY", unit=None):
    return {
        "target": target,
        "signal": signal,
        "source": source,
        "observed_at": _now(),
        "state": state,
        "code": "probe_ok" if state == "HEALTHY" else "probe_failed",
        "message": "Meting uitgevoerd" if state == "HEALTHY" else "Meting niet beschikbaar",
        "value": value,
        "unit": unit,
    }


def web_probe(url: str, health_url: str, target="web", timeout=5.0):
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = response.status
        result = [
            _obs(target, "https.reachable", "external_https", True),
            _obs(target, "https.status_code", "external_https", status),
            _obs(
                target,
                "https.latency_ms",
                "external_https",
                round((time.monotonic() - start) * 1000),
                unit="ms",
            ),
        ]
    except (urllib.error.URLError, TimeoutError, OSError):
        result = [_obs(target, "https.reachable", "external_https", False, "CRITICAL")]
    try:
        with urllib.request.urlopen(health_url, timeout=timeout) as response:
            status = response.status
        result.append(_obs(target, "health.status_code", "external_https", status))
    except (urllib.error.URLError, TimeoutError, OSError):
        result.append(_obs(target, "health.status_code", "external_https", None, "UNKNOWN"))
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        with (
            socket.create_connection((host, parsed.port or 443), timeout=timeout) as raw,
            ssl.create_default_context().wrap_socket(raw, server_hostname=host) as tls,
        ):
            expires = datetime.strptime(
                tls.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z"
            ).replace(tzinfo=UTC)
        result.append(
            _obs(
                target,
                "tls.days_remaining",
                "external_https",
                (expires - datetime.now(UTC)).days,
                unit="days",
            )
        )
    except (OSError, KeyError, ValueError, ssl.SSLError):
        result.append(_obs(target, "tls.days_remaining", "external_https", None, "UNKNOWN", "days"))
    return result


def backup_probe(path: str, target="backups", now=None):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = {
            "last_attempt_at",
            "last_success_at",
            "status",
            "backup_id",
            "database_bytes",
            "media_bytes",
            "checksum_verified",
            "git_commit",
        }
        if not isinstance(raw, dict) or any(k not in allowed for k in raw):
            raise ValueError
        result = [_obs(target, f"backup.{k}", "backup_status_file", v) for k, v in raw.items()]
        success = datetime.fromisoformat(str(raw["last_success_at"]).replace("Z", "+00:00"))
        result.append(
            _obs(
                target,
                "backup.success_age_seconds",
                "backup_status_file",
                int(((now or datetime.now(UTC)) - success).total_seconds()),
                unit="s",
            )
        )
        return result
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return [_obs(target, "backup.status", "backup_status_file", None, "UNKNOWN")]


def host_probe(backup_directory=None, target="host"):
    root = shutil.disk_usage(Path(os.path.abspath(os.sep)))
    result = [
        _obs(
            target,
            "host.uptime_seconds",
            "host_metrics",
            int(time.monotonic()),
            unit="s",
        ),
        _obs(
            target,
            "disk.root.used_percent",
            "host_metrics",
            round(root.used / root.total * 100, 2),
            unit="percent",
        ),
    ]
    if hasattr(os, "getloadavg"):
        result.append(_obs(target, "host.load_1m", "host_metrics", os.getloadavg()[0]))
    if backup_directory:
        try:
            result.append(
                _obs(
                    target,
                    "backup.directory_bytes",
                    "host_metrics",
                    sum(p.stat().st_size for p in Path(backup_directory).rglob("*") if p.is_file()),
                    unit="bytes",
                )
            )
        except OSError:
            result.append(
                _obs(
                    target,
                    "backup.directory_bytes",
                    "host_metrics",
                    None,
                    "UNKNOWN",
                    "bytes",
                )
            )
    return result


def _contract(url: str, required: set[str], timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        if response.status != 200 or int(response.headers.get("Content-Length", "0")) > 32768:
            raise ValueError("invalid observer response")
        value = json.loads(response.read(32769))
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("observer contract mismatch")
    return value


def database_probe(boundary_url: str, target="database"):
    keys = {
        "reachable",
        "version_major",
        "latency_ms",
        "size_bytes",
        "connections_percent",
        "migration_current",
    }
    try:
        data = _contract(f"{boundary_url}/v1/database", keys)
    except (OSError, ValueError, json.JSONDecodeError):
        return [_obs(target, "db.reachable", "database_contract", None, "UNKNOWN")]
    result = []
    for key, value in data.items():
        signal = f"db.{key}"
        state = "HEALTHY"
        if key == "reachable" and value is not True:
            state = "CRITICAL"
        elif key == "latency_ms":
            state = "CRITICAL" if value > 2000 else "WARNING" if value > 500 else state
        elif key == "connections_percent":
            state = "CRITICAL" if value > 90 else "WARNING" if value > 80 else state
        elif key == "migration_current" and value is not True:
            state = "WARNING"
        result.append(_obs(target, signal, "database_contract", value, state))
    return result


def mail_probe(boundary_url: str, target="mail"):
    keys = {
        "provider_state",
        "worker_running",
        "queue_count",
        "retryable_count",
        "failed_count",
        "oldest_queue_age_seconds",
        "last_accepted_age_seconds",
    }
    try:
        data = _contract(f"{boundary_url}/v1/mail", keys)
        if data["provider_state"] not in {"configured", "missing"}:
            raise ValueError("invalid provider state")
    except (OSError, ValueError, json.JSONDecodeError):
        return [_obs(target, "mail.provider_state", "mail_contract", None, "UNKNOWN")]
    result = []
    for key, value in data.items():
        state = "HEALTHY"
        if key == "provider_state" and value == "missing":
            state = "CRITICAL"
        elif key == "worker_running" and value is False:
            state = "CRITICAL" if data["queue_count"] > 0 else "WARNING"
        elif key == "failed_count" and value > 0:
            state = "CRITICAL" if value >= 10 else "WARNING"
        elif key == "oldest_queue_age_seconds":
            state = "CRITICAL" if value > 1800 else "WARNING" if value > 600 else state
        result.append(_obs(target, f"mail.{key}", "mail_contract", value, state))
    return result


def services_probe(boundary_url: str):
    allowed = {"caddy", "frontend", "backend", "db", "mail-worker"}
    item_keys = {"key", "running", "health", "restart_count", "uptime_seconds", "release_state"}
    try:
        envelope = _contract(f"{boundary_url}/v1/services", {"services"})
        if not isinstance(envelope["services"], list):
            raise ValueError("invalid services")
        result = []
        for item in envelope["services"]:
            if set(item) != item_keys or item["key"] not in allowed:
                raise ValueError("invalid service")
            if item["health"] not in {"healthy", "unhealthy", "none"}:
                raise ValueError("invalid service health")
            for key in item_keys - {"key"}:
                value = item[key]
                state = "HEALTHY"
                if key == "running" and value is False:
                    state = "CRITICAL"
                elif key == "health":
                    state = (
                        "CRITICAL"
                        if value == "unhealthy"
                        else "DEGRADED"
                        if value == "none"
                        else state
                    )
                elif key == "restart_count" and value > 0:
                    state = "WARNING"
                elif key == "release_state" and value != "current":
                    state = "DEGRADED"
                result.append(_obs(item["key"], f"service.{key}", "service_boundary", value, state))
        return result
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return [_obs("backend", "service.running", "service_boundary", None, "UNKNOWN")]
