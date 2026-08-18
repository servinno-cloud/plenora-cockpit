import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from test_foundation import login, owner

from app.cli import rotate_collector_secret
from app.models import (
    Collector,
    Environment,
    Incident,
    IncidentLifecycle,
    Observation,
    Product,
    Target,
)

TEST_COLLECTOR_SECRET = "collector-test-secret-with-32-characters"


def setup_monitoring(db):
    product = Product(code="plenora", name="Plenora")
    db.add(product)
    db.flush()
    environment = Environment(product_id=product.id, code="production", name="Production")
    db.add(environment)
    db.flush()
    for key, name in (
        ("web", "Web"),
        ("backups", "Backups"),
        ("host", "Host"),
        ("database", "Database"),
        ("mail", "Mail"),
        ("backend", "Backend"),
        ("collector", "Collector"),
    ):
        db.add(Target(environment_id=environment.id, key=key, name=name, component=name))
    collector = Collector(
        id=uuid.uuid4(),
        environment_id=environment.id,
        name="host-1",
        secret_hash=hashlib.sha256(TEST_COLLECTOR_SECRET.encode()).hexdigest(),
    )
    db.add(collector)
    db.commit()
    return environment, collector


def payload(
    environment,
    collector,
    sequence=1,
    value=503,
    snapshot_id=None,
    signal="https.status_code",
    state="HEALTHY",
    observed_at=None,
    target="web",
    source="external_https",
):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    observed = (observed_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    return {
        "schema": "snapshot.v1",
        "snapshot_id": str(snapshot_id or uuid.uuid4()),
        "collector_id": str(collector.id),
        "environment_id": str(environment.id),
        "sequence": sequence,
        "generated_at": now,
        "collector_version": "1.0.0",
        "observations": [
            {
                "target": target,
                "signal": signal,
                "source": source,
                "observed_at": observed,
                "state": state,
                "code": "probe_result",
                "message": "Meting uitgevoerd",
                "value": value,
            }
        ],
    }


def test_two_collector_identities_have_independent_sequences(client, db):
    environment, first = setup_monitoring(db)
    second = Collector(
        id=uuid.uuid4(), environment_id=environment.id, name="external-vps2",
        secret_hash=hashlib.sha256(b"second-collector-secret").hexdigest(),
    )
    db.add(second)
    db.commit()
    first_response = post(client, environment, payload(environment, first, sequence=1),
                          secret=TEST_COLLECTOR_SECRET)
    second_response = post(client, environment, payload(environment, second, sequence=1),
                           secret="second-collector-secret")
    assert first_response.status_code == 202
    assert second_response.status_code == 202


def post(client, environment, body, secret=TEST_COLLECTOR_SECRET):
    return client.post(
        f"/ingest/v1/environments/{environment.id}/snapshots",
        json=body,
        headers={"Authorization": f"Bearer {secret}", "Idempotency-Key": body["snapshot_id"]},
    )


def test_incident_antiflap_escalation_and_recovery(client, db):
    environment, collector = setup_monitoring(db)
    start = datetime.now(UTC) - timedelta(seconds=30)

    assert (
        post(
            client,
            environment,
            payload(environment, collector, 1, 600, signal="https.latency_ms", observed_at=start),
        ).status_code
        == 202
    )
    assert db.scalar(select(func.count()).select_from(Incident)) == 0

    second_at = start + timedelta(seconds=1)
    assert (
        post(
            client,
            environment,
            payload(
                environment, collector, 2, 600, signal="https.latency_ms", observed_at=second_at
            ),
        ).status_code
        == 202
    )
    incident = db.scalar(select(Incident))
    assert incident and incident.lifecycle == IncidentLifecycle.OPEN
    incident_id, original_fingerprint, first_seen = (
        incident.id,
        incident.fingerprint,
        incident.first_seen_at,
    )
    assert first_seen.replace(tzinfo=UTC) == start

    for sequence, value in ((3, 2501), (4, 2501)):
        assert (
            post(
                client,
                environment,
                payload(
                    environment,
                    collector,
                    sequence,
                    value,
                    signal="https.latency_ms",
                    observed_at=start + timedelta(seconds=sequence),
                ),
            ).status_code
            == 202
        )
    db.expire_all()
    incident = db.scalar(select(Incident))
    assert db.scalar(select(func.count()).select_from(Incident)) == 1
    assert incident.id == incident_id and incident.fingerprint == original_fingerprint
    assert incident.severity.value == "CRITICAL" and incident.first_seen_at == first_seen

    assert (
        post(
            client,
            environment,
            payload(
                environment,
                collector,
                5,
                100,
                signal="https.latency_ms",
                observed_at=start + timedelta(seconds=5),
            ),
        ).status_code
        == 202
    )
    db.expire_all()
    assert db.get(Incident, incident_id).lifecycle == IncidentLifecycle.OPEN

    assert (
        post(
            client,
            environment,
            payload(
                environment,
                collector,
                6,
                100,
                signal="https.latency_ms",
                observed_at=start + timedelta(seconds=6),
            ),
        ).status_code
        == 202
    )
    db.expire_all()
    resolved = db.get(Incident, incident_id)
    assert resolved.lifecycle == IncidentLifecycle.RESOLVED
    assert resolved.first_seen_at == first_seen


def test_unknown_bootstrap_does_not_create_incidents(client, db):
    environment, collector = setup_monitoring(db)
    for sequence in range(1, 6):
        body = payload(environment, collector, sequence, None, state="UNKNOWN")
        assert post(client, environment, body).status_code == 202
    assert db.scalar(select(func.count()).select_from(Observation)) == 5
    assert db.scalar(select(func.count()).select_from(Incident)) == 0


def test_service_signal_reuses_sprint1_incident_engine(client, db):
    environment, collector = setup_monitoring(db)
    for sequence in (1, 2):
        body = payload(
            environment,
            collector,
            sequence,
            "unhealthy",
            signal="service.health",
            state="CRITICAL",
            target="backend",
            source="service_boundary",
        )
        assert post(client, environment, body).status_code == 202
    incident = db.scalar(select(Incident))
    assert incident and incident.code == "service_unhealthy"
    incident_id = incident.id
    for sequence in (3, 4):
        body = payload(
            environment,
            collector,
            sequence,
            "healthy",
            signal="service.health",
            state="HEALTHY",
            target="backend",
            source="service_boundary",
        )
        assert post(client, environment, body).status_code == 202
    db.expire_all()
    assert db.get(Incident, incident_id).lifecycle == IncidentLifecycle.RESOLVED


def test_operator_api_exposes_health_and_history(client, db):
    environment, collector = setup_monitoring(db)
    for sequence in (1, 2):
        assert (
            post(client, environment, payload(environment, collector, sequence)).status_code == 202
        )
    owner(db)
    assert login(client).status_code == 200
    snapshot = client.get(f"/api/environments/{environment.id}/snapshot").json()
    assert snapshot["overall_state"] == "CRITICAL"
    assert snapshot["observations"][0]["code"] == "web_unhealthy"
    history = client.get(f"/api/environments/{environment.id}/observations").json()
    assert len(history) == 2
    assert client.get("/api/incidents").json()[0]["lifecycle"] == "OPEN"


def test_stale_healthy_signal_is_unknown(client, db):
    environment, collector = setup_monitoring(db)
    body = payload(
        environment,
        collector,
        1,
        200,
        observed_at=datetime.now(UTC) - timedelta(minutes=6),
    )
    assert post(client, environment, body).status_code == 202
    owner(db)
    assert login(client).status_code == 200
    snapshot = client.get(f"/api/environments/{environment.id}/snapshot").json()
    assert snapshot["overall_state"] == "UNKNOWN"
    assert snapshot["observations"][0]["stale"] is True


def test_ingest_is_idempotent_and_replay_protected(client, db):
    environment, collector = setup_monitoring(db)
    snapshot_id = uuid.uuid4()
    body = payload(environment, collector, snapshot_id=snapshot_id)
    assert post(client, environment, body).status_code == 202
    assert post(client, environment, body).json()["status"] == "duplicate"
    assert post(client, environment, payload(environment, collector, sequence=1)).status_code == 409


def test_ingest_rejects_credentials_schema_and_write_routes(client, db):
    environment, collector = setup_monitoring(db)
    body = payload(environment, collector)
    assert post(client, environment, body, "wrong").status_code == 401
    body["observations"][0]["recipient_email"] = "private@example.com"
    assert post(client, environment, body).status_code == 422
    unknown = payload(environment, collector)
    unknown["observations"][0]["signal"] = "filesystem.arbitrary_read"
    assert post(client, environment, unknown).status_code == 422
    for path in (
        "/api/remediate",
        "/api/actions",
        "/api/restart",
        "/api/deploy",
        "/api/restore",
    ):
        assert client.post(path, json={}).status_code == 404


def test_external_production_snapshot_passes_snapshot_v1_validation(client, db):
    environment, collector = setup_monitoring(db)
    body = payload(environment, collector)
    body["collector_version"] = "a" * 40
    observed_at = body["observations"][0]["observed_at"]
    body["observations"] = [
        {
            "target": "web",
            "signal": signal,
            "source": "external_https",
            "observed_at": observed_at,
            "state": "HEALTHY",
            "code": "probe_ok",
            "message": "Meting uitgevoerd",
            "value": value,
            "unit": unit,
        }
        for signal, value, unit in (
            ("https.reachable", True, None),
            ("https.status_code", 200, None),
            ("https.latency_ms", 42, "ms"),
            ("health.status_code", 200, None),
            ("tls.days_remaining", 60, "days"),
        )
    ] + [
        {
            "target": "collector",
            "signal": signal,
            "source": "collector_self",
            "observed_at": observed_at,
            "state": "HEALTHY",
            "code": "probe_ok",
            "message": "Meting uitgevoerd",
            "value": value,
            "unit": None,
        }
        for signal, value in (("collector.sequence", 1), ("collector.status", "online"))
    ]
    assert post(client, environment, body).status_code == 422
    body["collector_version"] = body["collector_version"][:32]
    assert post(client, environment, body).status_code == 202
    assert db.scalar(select(func.count()).select_from(Observation)) == 7


def test_collector_secret_rotation_preserves_binding_and_sequence(client, db, monkeypatch, capsys):
    environment, collector = setup_monitoring(db)
    assert post(client, environment, payload(environment, collector, sequence=1)).status_code == 202
    old_secret = TEST_COLLECTOR_SECRET
    new_secret = "new-collector-secret-that-is-at-least-32-characters"
    monkeypatch.setenv("COCKPIT_ROTATION_ENVIRONMENT_ID", str(environment.id))
    monkeypatch.setenv("COCKPIT_ROTATION_COLLECTOR_ID", str(collector.id))
    monkeypatch.setenv("COCKPIT_ROTATION_CURRENT_SECRET", old_secret)
    monkeypatch.setenv("COCKPIT_ROTATION_NEW_SECRET", new_secret)

    rotate_collector_secret()
    output = capsys.readouterr()
    assert old_secret not in output.out + output.err
    assert new_secret not in output.out + output.err
    db.expire_all()
    rotated = db.get(Collector, collector.id)
    assert rotated.environment_id == environment.id
    assert rotated.last_sequence == 1
    next_snapshot = payload(environment, collector, sequence=2)
    old_response = post(client, environment, next_snapshot, old_secret)
    next_snapshot["snapshot_id"] = str(uuid.uuid4())
    new_response = post(client, environment, next_snapshot, new_secret)
    assert old_response.status_code == 401
    assert new_response.status_code == 202
