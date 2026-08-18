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
    environments = client.get("/api/environments").json()
    assert environments[0]["name"] == "Production"
    assert environments[0]["product_name"] == "Plenora"
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
    response = post(client, environment, body)
    assert response.status_code == 422
    assert response.json() == {"error_code": "snapshot_invalid.field_type"}
    unknown = payload(environment, collector)
    unknown["observations"][0]["signal"] = "filesystem.arbitrary_read"
    response = post(client, environment, unknown)
    assert response.status_code == 422
    assert response.json() == {"error_code": "snapshot_invalid.observation_signal"}
    invalid_text = payload(
        environment, collector, signal="service.health", value="secret-internal-state",
        target="backend", source="service_boundary",
    )
    response = post(client, environment, invalid_text)
    assert response.status_code == 422
    assert response.json() == {"error_code": "snapshot_invalid.text_value"}
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
    response = post(client, environment, body)
    assert response.status_code == 422
    assert response.json() == {"error_code": "snapshot_invalid.collector_version"}
    body["collector_version"] = body["collector_version"][:32]
    assert post(client, environment, body).status_code == 202
    assert db.scalar(select(func.count()).select_from(Observation)) == 7


def test_exact_production_observer_snapshot_is_accepted(client, db):
    environment, collector = setup_monitoring(db)
    for key in ("caddy", "frontend", "db", "mail-worker", "observer"):
        db.add(Target(environment_id=environment.id, key=key, name=key, component="Services"))
    db.commit()
    current = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def item(target, signal, source, value, state="HEALTHY", unit=None):
        return {"target": target, "signal": signal, "source": source,
                "observed_at": current, "state": state,
                "code": "probe_ok" if state == "HEALTHY" else "probe_failed",
                "message": "Meting uitgevoerd", "value": value, "unit": unit}

    observations = [
        item("backups", "backup.last_attempt_at", "backup_status_file", current),
        item("backups", "backup.last_success_at", "backup_status_file", current),
        item("backups", "backup.status", "backup_status_file", "success"),
        item("backups", "backup.backup_id", "backup_status_file", "2026-08-18T120000Z"),
        item("backups", "backup.database_bytes", "backup_status_file", 1024),
        item("backups", "backup.media_bytes", "backup_status_file", 2048),
        item("backups", "backup.checksum_verified", "backup_status_file", True),
        item("backups", "backup.git_commit", "backup_status_file", "unknown"),
        item("backups", "backup.success_age_seconds", "backup_status_file", 0, unit="s"),
        item("host", "host.uptime_seconds", "host_metrics", 86400, unit="s"),
        item("host", "disk.root.used_bytes", "host_metrics", 4000, unit="bytes"),
        item("host", "disk.root.free_bytes", "host_metrics", 6000, unit="bytes"),
        item("host", "disk.root.inode_used_percent", "host_metrics", 10.0, unit="percent"),
        item("host", "disk.backup.used_bytes", "host_metrics", 5000, unit="bytes"),
        item("host", "disk.backup.free_bytes", "host_metrics", 15000, unit="bytes"),
        item("host", "disk.backup.inode_used_percent", "host_metrics", 5.0, unit="percent"),
        item("host", "host.load_1m", "host_metrics", 0.1),
        item("host", "host.load_5m", "host_metrics", 0.2),
        item("host", "host.load_15m", "host_metrics", 0.3),
        item("database", "db.version_major", "database_contract", 16),
        item("database", "db.size_bytes", "database_contract", 67108864),
        item("database", "db.connections_percent", "database_contract", 12.5),
        item("database", "db.django_migration_count", "database_contract", 42),
        item("database", "db.migration_current", "database_contract", None, "UNKNOWN"),
        item("database", "db.reachable", "database_contract", True),
        item("database", "db.latency_ms", "database_contract", 8),
    ]
    for target in ("caddy", "frontend", "backend", "db", "mail-worker"):
        observations.extend([
            item(target, "service.running", "service_boundary", True),
            item(target, "service.health", "service_boundary", "healthy"),
            item(target, "service.restart_count", "service_boundary", 0),
            item(target, "service.started_at", "service_boundary", current),
            item(target, "service.image_identifier", "service_boundary",
                 "sha256:0123456789abcdef"),
        ])
    observations.extend([
        item("mail", "mail.provider_state", "mail_contract", None, "UNKNOWN"),
        item("observer", "collector.sequence", "collector_self", 1),
        item("observer", "collector.status", "collector_self", "online"),
    ])
    body = payload(environment, collector)
    body["collector_version"] = "0123456789abcdef0123456789abcdef"
    body["observations"] = observations
    response = post(client, environment, body)
    assert response.status_code == 202
    assert body["collector_version"] == "0123456789abcdef0123456789abcdef"
    values = {item["signal"]: item["value"] for item in body["observations"]}
    assert values["backup.git_commit"] == "unknown"
    assert values["db.django_migration_count"] == 42
    assert values["db.migration_current"] is None


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


def test_django_migration_metadata_does_not_claim_unknown_expectation_is_healthy(client, db):
    environment, collector = setup_monitoring(db)
    count = payload(
        environment,
        collector,
        sequence=1,
        value=42,
        signal="db.django_migration_count",
        target="database",
        source="database_contract",
    )
    unknown = payload(
        environment,
        collector,
        sequence=2,
        value=None,
        signal="db.migration_current",
        state="UNKNOWN",
        target="database",
        source="database_contract",
    )
    assert post(client, environment, count).status_code == 202
    assert post(client, environment, unknown).status_code == 202
    observations = db.scalars(
        select(Observation).where(Observation.environment_id == environment.id)
    ).all()
    states = {item.signal: item.state.value for item in observations}
    assert states["db.django_migration_count"] == "HEALTHY"
    assert states["db.migration_current"] == "UNKNOWN"
    owner(db)
    assert login(client).status_code == 200
    snapshot = client.get(f"/api/environments/{environment.id}/snapshot").json()
    assert snapshot["component_states"]["Database"] == "HEALTHY"
