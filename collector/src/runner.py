import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .probes import (
    backup_probe,
    database_probe,
    host_probe,
    mail_probe,
    services_probe,
    web_probe,
)

MAX_PENDING = 50


def build_snapshot(config: dict[str, str], sequence: int) -> dict:
    observations = web_probe(config["web_url"], config["health_url"])
    if config["profile"] == "development":
        observations += backup_probe(config["backup_status_path"])
        observations += host_probe()
        observations += database_probe(config["boundary_url"])
        observations += mail_probe(config["boundary_url"])
        observations += services_probe(config["boundary_url"])
    observations += [
        {
            "target": "collector",
            "signal": "collector.sequence",
            "source": "collector_self",
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "state": "HEALTHY",
            "code": "probe_ok",
            "message": "Meting uitgevoerd",
            "value": sequence,
            "unit": None,
        },
        {
            "target": "collector",
            "signal": "collector.status",
            "source": "collector_self",
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "state": "HEALTHY",
            "code": "probe_ok",
            "message": "Meting uitgevoerd",
            "value": "online",
            "unit": None,
        },
    ]
    return {
        "schema": "snapshot.v1",
        "snapshot_id": str(uuid.uuid4()),
        "collector_id": config["collector_id"],
        "environment_id": config["environment_id"],
        "sequence": sequence,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "collector_version": config.get("release", "development")[:32],
        "observations": observations,
    }


def send(snapshot: dict, config: dict[str, str]) -> None:
    payload = json.dumps(snapshot, separators=(",", ":")).encode()
    url = (
        f"{config['ingest_url'].rstrip('/')}/ingest/v1/environments/"
        f"{snapshot['environment_id']}/snapshots"
    )
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['collector_secret']}",
            "Idempotency-Key": snapshot["snapshot_id"],
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 202:
            raise RuntimeError("ingest rejected")


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"sequence": 0, "pending": []}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state.get("sequence"), int) or not isinstance(state.get("pending"), list):
        raise TypeError("invalid collector state")
    return state


def save_state(state_path: Path, state: dict) -> None:
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(state_path)


def run_once(config: dict[str, str], state_path: str = "/state/state.json") -> dict:
    state_file = Path(state_path)
    state = load_state(state_file)
    highest = max([state["sequence"], *(item["sequence"] for item in state["pending"])])
    state["pending"].append(build_snapshot(config, highest + 1))
    # Preserve oldest retry items; discard newest overflow until delivery recovers.
    state["pending"] = state["pending"][:MAX_PENDING]
    save_state(state_file, state)
    for pending in list(state["pending"]):
        try:
            send(pending, config)
        except urllib.error.HTTPError as error:
            if error.code not in {400, 409, 413, 422}:
                break
            error_codes = {
                400: "invalid_envelope",
                409: "sequence_replayed",
                413: "snapshot_too_large",
                422: "snapshot_invalid",
            }
            print(
                f"snapshot rejected status={error.code} error_code={error_codes[error.code]}",
                file=sys.stderr,
            )
            state["pending"].remove(pending)
            state["sequence"] = pending["sequence"]
            save_state(state_file, state)
            continue
        except OSError:
            break
        state["pending"].remove(pending)
        state["sequence"] = pending["sequence"]
        save_state(state_file, state)
    return state


def environment_config() -> dict[str, str]:
    required = {
        "collector_id": "COCKPIT_COLLECTOR_ID",
        "environment_id": "COCKPIT_ENVIRONMENT_ID",
        "collector_secret": "COCKPIT_COLLECTOR_SECRET",
        "ingest_url": "COCKPIT_INGEST_URL",
        "web_url": "COCKPIT_WEB_URL",
        "health_url": "COCKPIT_HEALTH_URL",
        "profile": "COCKPIT_PROBE_PROFILE",
    }
    config = {key: os.environ.get(name, "") for key, name in required.items()}
    if any(not value for value in config.values()):
        raise RuntimeError("collector configuration incomplete")
    if config["profile"] not in {"development", "external"}:
        raise RuntimeError("COCKPIT_PROBE_PROFILE must be development or external")
    if config["profile"] == "development":
        optional = {
            "boundary_url": "COCKPIT_BOUNDARY_URL",
            "backup_status_path": "COCKPIT_BACKUP_STATUS_PATH",
        }
        config.update({key: os.environ.get(name, "") for key, name in optional.items()})
        if any(not config[key] for key in optional):
            raise RuntimeError("development fixture configuration incomplete")
    config["release"] = os.environ.get("COCKPIT_RELEASE", "development")
    return config


def main() -> None:
    config = environment_config()
    interval = int(os.environ.get("COCKPIT_POLL_INTERVAL_SECONDS", "60"))
    while True:
        run_once(config)
        time.sleep(interval)


if __name__ == "__main__":
    main()
