import uuid
from datetime import UTC, datetime

from app.health_semantics import aggregate_health
from app.models import HealthState, Observation
from app.monitoring import classify


def observation(component, signal, state=HealthState.HEALTHY, text_value=None, target_id=None):
    return Observation(
        id=uuid.uuid4(), snapshot_id=None, environment_id=uuid.uuid4(),
        target_id=target_id or uuid.uuid4(), component=component, signal=signal,
        code="ok", state=state, observed_at=datetime.now(UTC), numeric_value=None,
        text_value=text_value, unit=None, message=None, source="test",
    )


def test_healthy_database_ignores_only_unknown_migration_and_mail_is_optional():
    service_target = uuid.uuid4()
    backend_target = uuid.uuid4()
    items = [
        observation("Web", "https.reachable"),
        observation("Backend", "service.running", target_id=backend_target),
        observation("Backups", "backup.status"),
        observation("Host", "host.uptime_seconds"),
        observation("Services", "service.running", target_id=service_target),
        observation("Services", "service.health", HealthState.UNKNOWN, "none", service_target),
        observation("Database", "db.reachable"),
        observation("Database", "db.version_major"),
        observation("Database", "db.latency_ms"),
        observation("Database", "db.size_bytes"),
        observation("Database", "db.connections_percent"),
        observation("Database", "db.django_migration_count"),
        observation("Database", "db.migration_current", HealthState.UNKNOWN),
        observation("Mail", "mail.provider_state", HealthState.UNKNOWN),
    ]
    stale = {item.id: False for item in items}
    components, services, overall = aggregate_health(
        items, stale, {service_target: "caddy", backend_target: "backend"}
    )
    assert components["Database"] == "HEALTHY"
    assert components["Mail"] == "UNKNOWN"
    assert services["caddy"] == "HEALTHY"
    assert overall == "HEALTHY"
    assert classify("service.health", "none", HealthState.UNKNOWN)[0] == HealthState.UNKNOWN


def test_unreachable_database_and_unhealthy_service_are_critical():
    database = observation("Database", "db.reachable", HealthState.CRITICAL)
    service_target = uuid.uuid4()
    service = observation(
        "Services", "service.health", HealthState.CRITICAL, "unhealthy", service_target
    )
    components, services, overall = aggregate_health(
        [database, service],
        {database.id: False, service.id: False},
        {service_target: "caddy"},
    )
    assert components["Database"] == "CRITICAL"
    assert services["caddy"] == "CRITICAL"
    assert overall == "CRITICAL"
