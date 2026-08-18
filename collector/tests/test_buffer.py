import io
import json
import urllib.error
from pathlib import Path

from src import runner

CONFIG = {
    "collector_id": "22222222-2222-4222-8222-222222222222",
    "environment_id": "11111111-1111-4111-8111-111111111111",
    "collector_secret": "test-secret",
    "ingest_url": "http://backend:8000",
    "web_url": "https://example.test",
    "health_url": "https://example.test/health",
    "backup_status_path": "/backup/status.json",
    "boundary_url": "http://observer:8080",
    "profile": "development",
}


def snapshot(sequence):
    return {
        "schema": "snapshot.v1",
        "snapshot_id": f"snapshot-{sequence}",
        "collector_id": CONFIG["collector_id"],
        "environment_id": CONFIG["environment_id"],
        "sequence": sequence,
        "generated_at": "2026-08-17T12:00:00Z",
        "collector_version": "1.0.0",
        "observations": [],
    }


def test_buffer_caps_at_50_and_preserves_oldest(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "sequence": 0,
                "pending": [snapshot(sequence) for sequence in range(1, 51)],
            }
        )
    )
    monkeypatch.setattr(runner, "build_snapshot", lambda config, sequence: snapshot(sequence))
    monkeypatch.setattr(runner, "send", lambda item, config: (_ for _ in ()).throw(OSError()))
    state = runner.run_once(CONFIG, str(state_path))
    assert len(state["pending"]) == 50
    assert [item["sequence"] for item in state["pending"]] == list(range(1, 51))


def test_retry_keeps_identity_sequence_and_restart_progress(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(runner, "build_snapshot", lambda config, sequence: snapshot(sequence))
    monkeypatch.setattr(runner, "send", lambda item, config: (_ for _ in ()).throw(OSError()))
    first = runner.run_once(CONFIG, str(state_path))
    assert first["pending"] == [snapshot(1)]

    delivered = []
    monkeypatch.setattr(runner, "send", lambda item, config: delivered.append(item.copy()))
    second = runner.run_once(CONFIG, str(state_path))
    assert [(item["snapshot_id"], item["sequence"]) for item in delivered] == [
        ("snapshot-1", 1),
        ("snapshot-2", 2),
    ]
    assert second == {"sequence": 2, "pending": []}

    delivered.clear()
    restarted = runner.run_once(CONFIG, str(state_path))
    assert [(item["snapshot_id"], item["sequence"]) for item in delivered] == [("snapshot-3", 3)]
    assert restarted == {"sequence": 3, "pending": []}


def test_success_removes_each_item_durably(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(runner, "build_snapshot", lambda config, sequence: snapshot(sequence))
    monkeypatch.setattr(runner, "send", lambda item, config: None)
    state = runner.run_once(CONFIG, str(state_path))
    persisted = json.loads(Path(state_path).read_text())
    assert state["pending"] == [] and persisted == state


def test_permanent_rejection_does_not_block_new_snapshots(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"sequence": 0, "pending": [snapshot(1)]}))
    monkeypatch.setattr(runner, "build_snapshot", lambda config, sequence: snapshot(sequence))
    delivered = []

    def reject_old(item, config):
        if item["sequence"] == 1:
            raise urllib.error.HTTPError("http://ingest", 400, "stale", {}, io.BytesIO())
        delivered.append(item["sequence"])

    monkeypatch.setattr(runner, "send", reject_old)
    state = runner.run_once(CONFIG, str(state_path))
    assert delivered == [2]
    assert state == {"sequence": 2, "pending": []}
    diagnostic = capsys.readouterr()
    assert "snapshot rejected status=400 error_code=invalid_envelope" in diagnostic.err
    assert CONFIG["collector_secret"] not in diagnostic.out + diagnostic.err


def test_422_diagnostic_is_safe_and_does_not_read_response_body(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    response_body = io.BytesIO(b'sensitive payload details must not be logged')
    monkeypatch.setattr(runner, "build_snapshot", lambda config, sequence: snapshot(sequence))
    monkeypatch.setattr(
        runner,
        "send",
        lambda item, config: (_ for _ in ()).throw(
            urllib.error.HTTPError("http://ingest", 422, "invalid", {}, response_body)
        ),
    )
    runner.run_once(CONFIG, str(state_path))
    diagnostic = capsys.readouterr()
    assert diagnostic.err.strip() == "snapshot rejected status=422 error_code=snapshot_invalid"
    assert "sensitive payload" not in diagnostic.out + diagnostic.err
    assert CONFIG["collector_secret"] not in diagnostic.out + diagnostic.err
