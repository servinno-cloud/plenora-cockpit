import pytest

from src import probes
from src.database_catalog import DATABASE_QUERIES, query_for


def test_database_catalog_is_closed_and_contains_no_business_tables():
    assert set(DATABASE_QUERIES) == {
        "version_major",
        "size_bytes",
        "connections_percent",
        "migration_current",
    }
    combined = " ".join(DATABASE_QUERIES.values()).lower()
    for forbidden in ("people", "shifts", "leave", "notes", "mail", "insert", "update", "delete"):
        assert forbidden not in combined
    with pytest.raises(KeyError):
        query_for("SELECT * FROM people")


@pytest.mark.parametrize("latency,state", [(8, "HEALTHY"), (600, "WARNING"), (2500, "CRITICAL")])
def test_database_latency_policies(monkeypatch, latency, state):
    monkeypatch.setattr(
        probes,
        "_contract",
        lambda *args: {
            "reachable": True,
            "version_major": 16,
            "latency_ms": latency,
            "size_bytes": 1000,
            "connections_percent": 20,
            "migration_current": True,
        },
    )
    result = probes.database_probe("http://fixture")
    assert next(item for item in result if item["signal"] == "db.latency_ms")["state"] == state


def test_database_unreachable_connections_and_migration(monkeypatch):
    monkeypatch.setattr(
        probes,
        "_contract",
        lambda *args: {
            "reachable": False,
            "version_major": 16,
            "latency_ms": 5,
            "size_bytes": 1000,
            "connections_percent": 95,
            "migration_current": False,
        },
    )
    states = {item["signal"]: item["state"] for item in probes.database_probe("x")}
    assert states["db.reachable"] == "CRITICAL"
    assert states["db.connections_percent"] == "CRITICAL"
    assert states["db.migration_current"] == "WARNING"


@pytest.mark.parametrize(
    "worker,queue,failed,age,provider,expected",
    [
        (True, 0, 0, 0, "configured", "HEALTHY"),
        (False, 0, 0, 0, "configured", "WARNING"),
        (False, 2, 0, 0, "configured", "CRITICAL"),
        (True, 0, 1, 0, "configured", "WARNING"),
        (True, 1, 0, 1900, "configured", "CRITICAL"),
        (True, 0, 0, 0, "missing", "CRITICAL"),
    ],
)
def test_mail_policies(monkeypatch, worker, queue, failed, age, provider, expected):
    monkeypatch.setattr(
        probes,
        "_contract",
        lambda *args: {
            "provider_state": provider,
            "worker_running": worker,
            "queue_count": queue,
            "retryable_count": 0,
            "failed_count": failed,
            "oldest_queue_age_seconds": age,
            "last_accepted_age_seconds": 10,
        },
    )
    result = probes.mail_probe("x")
    assert (
        max((item["state"] for item in result), key={"HEALTHY": 0, "WARNING": 1, "CRITICAL": 2}.get)
        == expected
    )


def test_services_policies_and_unknown_rejected(monkeypatch):
    monkeypatch.setattr(
        probes,
        "_contract",
        lambda *args: {
            "services": [
                {
                    "key": "backend",
                    "running": False,
                    "health": "unhealthy",
                    "restart_count": 2,
                    "uptime_seconds": 10,
                    "release_state": "current",
                },
                {
                    "key": "frontend",
                    "running": True,
                    "health": "none",
                    "restart_count": 0,
                    "uptime_seconds": 10,
                    "release_state": "current",
                },
            ]
        },
    )
    result = probes.services_probe("x")
    assert any(item["state"] == "CRITICAL" for item in result if item["target"] == "backend")
    assert any(item["state"] == "DEGRADED" for item in result if item["target"] == "frontend")
    monkeypatch.setattr(probes, "_contract", lambda *args: {"services": [{"key": "unknown"}]})
    assert probes.services_probe("x")[0]["state"] == "UNKNOWN"
