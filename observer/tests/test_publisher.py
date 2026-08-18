import io
import json
import urllib.error

import pytest

import publisher


def snapshot(sequence):
    return {"snapshot_id": f"id-{sequence}", "sequence": sequence}


def test_push_buffer_caps_at_50_and_preserves_oldest(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"sequence": 0, "pending": [snapshot(i) for i in range(1, 51)]}))
    monkeypatch.setattr(publisher, "build_snapshot", lambda config, sequence: snapshot(sequence))
    monkeypatch.setattr(publisher, "send", lambda item, config: (_ for _ in ()).throw(OSError()))
    state = publisher.run_once({}, path)
    assert [item["sequence"] for item in state["pending"]] == list(range(1, 51))


def test_successful_push_removes_item_and_preserves_sequence(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    monkeypatch.setattr(publisher, "build_snapshot", lambda config, sequence: snapshot(sequence))
    delivered = []
    monkeypatch.setattr(publisher, "send", lambda item, config: delivered.append(item.copy()))
    assert publisher.run_once({}, path) == {"sequence": 1, "pending": []}
    assert delivered == [snapshot(1)]


def test_publisher_requires_scoped_identity_and_exact_backup_path(monkeypatch):
    values = {
        "PLENORA_OBSERVER_ID": "observer", "COCKPIT_ENVIRONMENT_ID": "environment",
        "PLENORA_OBSERVER_TOKEN": "x" * 32,
        "COCKPIT_INGEST_URL": "https://cockpit.plenora.nl",
        "PLENORA_MONITOR_DATABASE_URL": "postgresql://monitor@db/plenora",
        "PLENORA_OBSERVER_RELEASE": "release",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    config = publisher.environment_config()
    assert config["backup_status_path"] == "/status/backup-status.json"
    monkeypatch.delenv("PLENORA_OBSERVER_TOKEN")
    with pytest.raises(RuntimeError, match="configuration incomplete"):
        publisher.environment_config()


def test_snapshot_keeps_mail_unknown_without_contract(monkeypatch):
    monkeypatch.setattr(publisher, "backup_probe", lambda *args: [])
    monkeypatch.setattr(publisher, "host_observations", lambda: [])
    monkeypatch.setattr(publisher, "database_connection_probe", lambda *args: [])
    monkeypatch.setattr(publisher, "service_observations", lambda: [])
    config = {"backup_status_path": "exact", "database_url": "db", "collector_id": "c",
              "environment_id": "e", "release": "release"}
    mail = next(item for item in publisher.build_snapshot(config, 1)["observations"]
                if item["target"] == "mail")
    assert mail["state"] == "UNKNOWN" and mail["code"] == "integration_disabled"


def test_release_is_bounded_to_snapshot_contract(monkeypatch):
    monkeypatch.setattr(publisher, "backup_probe", lambda *args: [])
    monkeypatch.setattr(publisher, "host_observations", lambda: [])
    monkeypatch.setattr(publisher, "database_connection_probe", lambda *args: [])
    monkeypatch.setattr(publisher, "service_observations", lambda: [])
    config = {"backup_status_path": "exact", "database_url": "db", "collector_id": "c",
              "environment_id": "e", "release": "a" * 40}
    assert publisher.build_snapshot(config, 1)["collector_version"] == "a" * 32


def test_safe_422_diagnostic_logs_only_closed_code(monkeypatch, tmp_path, capsys):
    secret = "synthetic-secret-never-log-000000000000"
    payload_marker = "synthetic-payload-never-log"
    monkeypatch.setattr(
        publisher,
        "build_snapshot",
        lambda config, sequence: {"snapshot_id": payload_marker, "sequence": sequence},
    )

    def reject(*args):
        body = io.BytesIO(b'{"error_code":"snapshot_invalid.collector_version"}')
        raise urllib.error.HTTPError("https://ingest", 422, "invalid", {}, body)

    monkeypatch.setattr(publisher, "send", reject)
    state = publisher.run_once({"secret": secret}, tmp_path / "state.json")
    diagnostic = capsys.readouterr().err.strip()
    assert diagnostic == (
        "snapshot rejected status=422 error_code=snapshot_invalid.collector_version"
    )
    assert secret not in diagnostic and payload_marker not in diagnostic
    assert state == {"sequence": 1, "pending": []}


def test_running_service_without_docker_healthcheck_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(
        publisher,
        "live_services",
        lambda: {"services": [{
            "service_key": "caddy", "running": True, "health": "none",
            "restart_count": 0, "started_at": "2026-08-18T12:00:00Z",
            "image_identifier": "sha256:0123456789abcdef",
        }]},
    )
    observations = publisher.service_observations()
    states = {item["signal"]: item["state"] for item in observations}
    assert states["service.running"] == "HEALTHY"
    assert states["service.health"] == "UNKNOWN"
