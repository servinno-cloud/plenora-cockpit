import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from server import HOST_STATUS, live_services, read_closed_json
from src.probes import backup_probe, database_connection_probe

MAX_PENDING = 50


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def observation(target, signal, source, value, state="HEALTHY", unit=None):
    code = (
        "probe_ok"
        if state == "HEALTHY"
        else "integration_disabled"
        if target == "mail" and state == "UNKNOWN"
        else "probe_failed"
    )
    return {
        "target": target,
        "signal": signal,
        "source": source,
        "observed_at": now(),
        "state": state,
        "code": code,
        "message": "Meting uitgevoerd" if state == "HEALTHY" else "Integratie nog niet gekoppeld",
        "value": value,
        "unit": unit,
    }


def host_observations():
    keys = {
        "timestamp", "uptime_seconds", "root_total_bytes", "root_used_bytes",
        "root_free_bytes", "root_inode_used_percent", "backup_total_bytes",
        "backup_used_bytes", "backup_free_bytes", "backup_inode_used_percent",
        "load_1m", "load_5m", "load_15m",
    }
    try:
        data = read_closed_json(HOST_STATUS, keys)
    except (OSError, ValueError, json.JSONDecodeError):
        return [observation("host", "host.uptime_seconds", "host_metrics", None, "UNKNOWN", "s")]
    mapping = {
        "uptime_seconds": ("host.uptime_seconds", "s"),
        "root_used_bytes": ("disk.root.used_bytes", "bytes"),
        "root_free_bytes": ("disk.root.free_bytes", "bytes"),
        "root_inode_used_percent": ("disk.root.inode_used_percent", "percent"),
        "backup_used_bytes": ("disk.backup.used_bytes", "bytes"),
        "backup_free_bytes": ("disk.backup.free_bytes", "bytes"),
        "backup_inode_used_percent": ("disk.backup.inode_used_percent", "percent"),
        "load_1m": ("host.load_1m", None),
        "load_5m": ("host.load_5m", None),
        "load_15m": ("host.load_15m", None),
    }
    return [observation("host", signal, "host_metrics", data[key], unit=unit)
            for key, (signal, unit) in mapping.items()]


def service_observations():
    try:
        services = live_services()["services"]
    except (OSError, ValueError, LookupError, json.JSONDecodeError):
        return [observation("backend", "service.running", "service_boundary", None, "UNKNOWN")]
    result = []
    for item in services:
        target = item["service_key"]
        for key in ("running", "health", "restart_count", "started_at", "image_identifier"):
            value = item[key]
            state = "HEALTHY"
            if key == "running" and value is False:
                state = "CRITICAL"
            elif key == "health" and value in {"unhealthy", "starting", "none"}:
                state = "CRITICAL" if value == "unhealthy" else "DEGRADED"
            elif key == "restart_count" and value > 0:
                state = "WARNING"
            result.append(observation(target, f"service.{key}", "service_boundary", value, state))
    return result


def build_snapshot(config, sequence):
    observations = backup_probe(config["backup_status_path"])
    observations += host_observations()
    observations += database_connection_probe(config["database_url"])
    observations += service_observations()
    observations.append(
        observation("mail", "mail.provider_state", "mail_contract", None, "UNKNOWN")
    )
    observations += [
        observation("observer", "collector.sequence", "collector_self", sequence),
        observation("observer", "collector.status", "collector_self", "online"),
    ]
    return {
        "schema": "snapshot.v1",
        "snapshot_id": str(uuid.uuid4()),
        "collector_id": config["collector_id"],
        "environment_id": config["environment_id"],
        "sequence": sequence,
        "generated_at": now(),
        "collector_version": config["release"],
        "observations": observations,
    }


def send(snapshot, config):
    url = (f"{config['ingest_url'].rstrip('/')}/ingest/v1/environments/"
           f"{config['environment_id']}/snapshots")
    request = urllib.request.Request(url, data=json.dumps(snapshot, separators=(",", ":")).encode(),
        method="POST", headers={"Content-Type": "application/json",
        "Authorization": f"Bearer {config['secret']}",
        "Idempotency-Key": snapshot["snapshot_id"]})
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 202:
            raise RuntimeError("ingest rejected")


def load_state(path):
    if not path.exists():
        return {"sequence": 0, "pending": []}
    value = json.loads(path.read_text())
    if not isinstance(value.get("sequence"), int) or not isinstance(value.get("pending"), list):
        raise TypeError("invalid publisher state")
    return value


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)


def run_once(config, state_path=Path("/state/state.json")):
    state = load_state(state_path)
    highest = max([state["sequence"], *(item["sequence"] for item in state["pending"])])
    state["pending"].append(build_snapshot(config, highest + 1))
    state["pending"] = state["pending"][:MAX_PENDING]
    save_state(state_path, state)
    for item in list(state["pending"]):
        try:
            send(item, config)
        except urllib.error.HTTPError as error:
            if error.code not in {400, 409, 413, 422}:
                break
        except OSError:
            break
        state["pending"].remove(item)
        state["sequence"] = item["sequence"]
        save_state(state_path, state)
    return state


def environment_config():
    mapping = {"collector_id": "PLENORA_OBSERVER_ID", "environment_id": "COCKPIT_ENVIRONMENT_ID",
        "secret": "PLENORA_OBSERVER_TOKEN", "ingest_url": "COCKPIT_INGEST_URL",
        "database_url": "PLENORA_MONITOR_DATABASE_URL"}
    config = {key: os.getenv(name, "") for key, name in mapping.items()}
    config["backup_status_path"] = "/var/backups/plenora/status.json"
    config["release"] = os.getenv("PLENORA_OBSERVER_RELEASE", "")
    if any(not value for value in config.values()):
        raise RuntimeError("observer publisher configuration incomplete")
    if len(config["secret"]) < 32:
        raise RuntimeError("observer token must contain at least 32 characters")
    return config


def main():
    config = environment_config()
    interval = int(os.getenv("PLENORA_OBSERVER_POLL_SECONDS", "60"))
    while True:
        run_once(config)
        time.sleep(interval)


if __name__ == "__main__":
    main()
