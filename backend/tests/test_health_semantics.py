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


def test_existing_local_backup_health_semantics_remain_green():
    assert classify("backup.status", "success", HealthState.HEALTHY) == (
        HealthState.HEALTHY,
        "ok",
    )
    assert classify("backup.success_age_seconds", 26 * 3600, HealthState.HEALTHY) == (
        HealthState.HEALTHY,
        "ok",
    )
    assert classify("backup.checksum_verified", True, HealthState.HEALTHY) == (
        HealthState.HEALTHY,
        "ok",
    )


def test_offsite_health_status_does_not_require_a_measurement():
    assert classify("offsite.health", None, HealthState.HEALTHY) == (
        HealthState.HEALTHY,
        "ok",
    )
    assert classify("offsite.health", None, HealthState.WARNING) == (
        HealthState.WARNING,
        "offsite_backup_health",
    )
    assert classify("offsite.health", None, HealthState.CRITICAL) == (
        HealthState.CRITICAL,
        "offsite_backup_health",
    )
    assert classify("offsite.health", None, HealthState.DEGRADED) == (
        HealthState.UNKNOWN,
        "signal_unknown",
    )
    assert classify("offsite.health", None, HealthState.UNKNOWN) == (
        HealthState.UNKNOWN,
        "signal_unknown",
    )


def test_recent_verified_local_backup_ignores_non_applicable_offsite_pending_age():
    items = [
        observation("Backups", "backup.status"),
        observation("Backups", "backup.success_age_seconds"),
        observation("Backups", "backup.checksum_verified"),
        observation("Backups", "backup.database_bytes"),
        observation("Backups", "backup.media_bytes"),
        observation("Backups", "offsite.health"),
        observation("Backups", "offsite.pending_age_seconds", HealthState.UNKNOWN),
    ]

    components, _, _ = aggregate_health(
        items, {item.id: False for item in items}, {}
    )

    assert components["Backups"] == "HEALTHY"


def test_missing_local_backup_status_remains_unknown():
    items = [
        observation("Backups", "backup.status", HealthState.UNKNOWN),
        observation("Backups", "offsite.health"),
        observation("Backups", "offsite.pending_age_seconds", HealthState.UNKNOWN),
    ]

    components, _, _ = aggregate_health(
        items, {item.id: False for item in items}, {}
    )

    assert components["Backups"] == "UNKNOWN"


def test_local_backup_failures_and_offsite_health_keep_existing_severity():
    assert classify("backup.checksum_verified", False, HealthState.HEALTHY) == (
        HealthState.CRITICAL,
        "backup_unhealthy",
    )
    assert classify("backup.success_age_seconds", 26 * 3600 + 1, HealthState.HEALTHY) == (
        HealthState.WARNING,
        "backup_unhealthy",
    )
    assert classify("backup.success_age_seconds", 48 * 3600 + 1, HealthState.HEALTHY) == (
        HealthState.CRITICAL,
        "backup_unhealthy",
    )

    items = [
        observation("Backups", "backup.status"),
        observation("Backups", "offsite.health", HealthState.CRITICAL),
        observation("Backups", "offsite.pending_age_seconds", HealthState.UNKNOWN),
    ]
    components, _, _ = aggregate_health(
        items, {item.id: False for item in items}, {}
    )
    assert components["Backups"] == "CRITICAL"
