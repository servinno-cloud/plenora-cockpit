import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from test_monitoring import payload, post, setup_monitoring

from app.config import get_settings
from app.models import (
    HealthState,
    Incident,
    IncidentLifecycle,
    NotificationDeliveryState,
    NotificationEvent,
    NotificationEventType,
    Observation,
    Target,
)
from app.monitoring import fingerprint
from app.notifications import record_worker_heartbeat
from app.self_monitoring import collector_inventory, run_self_monitoring


def settings(**updates):
    values = {
        "collector_freshness_warning_seconds": 120,
        "collector_freshness_critical_seconds": 300,
        "notification_worker_warning_seconds": 45,
        "notification_worker_critical_seconds": 75,
        "notification_outbox_warning_seconds": 600,
        "notification_outbox_critical_seconds": 1800,
        "notification_email_to": "operations@example.test",
        "notification_email_from": "cockpit@example.test",
        "notification_smtp_host": "smtp.example.test",
    }
    values.update(updates)
    return get_settings().model_copy(update=values)


def notification_target(db, environment):
    target = Target(
        environment_id=environment.id,
        key="cockpit-notifications",
        name="Cockpit notifications",
        component="Cockpit notifications",
    )
    db.add(target)
    db.commit()
    return target


def lifecycle_event(db, environment, created_at, delivery_state):
    target = db.scalar(select(Target).where(
        Target.environment_id == environment.id,
        Target.key == "web",
    ))
    incident = Incident(
        environment_id=environment.id,
        target_id=target.id,
        fingerprint=uuid.uuid4().hex,
        component="Web",
        code="web_unhealthy",
        title="Web endpoint is niet gezond",
        severity=HealthState.WARNING,
        lifecycle=IncidentLifecycle.OPEN,
        source="test",
        first_seen_at=created_at,
        last_seen_at=created_at,
        occurrence_count=2,
        policy_version="test.v1",
    )
    db.add(incident)
    db.flush()
    event = NotificationEvent(
        incident_id=incident.id,
        event_type=NotificationEventType.OPENED,
        deduplication_key=f"test:{uuid.uuid4()}",
        to_severity=HealthState.WARNING,
        delivery_state=delivery_state,
        created_at=created_at,
    )
    db.add(event)
    db.commit()
    return event


def test_fresh_collector_and_fresh_unknown_target_do_not_open_incident(client, db):
    environment, collector = setup_monitoring(db)
    assert post(
        client,
        environment,
        payload(environment, collector, value=None, state="UNKNOWN"),
    ).status_code == 202
    db.refresh(collector)
    now = datetime.now(UTC)

    run_self_monitoring(db, settings(), now)
    run_self_monitoring(db, settings(), now + timedelta(seconds=30))

    assert db.scalar(select(func.count()).select_from(Incident)) == 0
    latest = db.scalar(select(Observation).where(
        Observation.signal == "collector.freshness_seconds"
    ).order_by(Observation.observed_at.desc()))
    assert latest.state == HealthState.HEALTHY
    inventory = collector_inventory(db, settings(), now)
    assert inventory[0]["status"] == "HEALTHY"
    assert inventory[0]["last_successful_run_at"] == collector.last_seen_at


def test_stale_collector_opens_escalates_deduplicates_and_resolves_after_restart(db):
    environment, collector = setup_monitoring(db)
    now = datetime.now(UTC)
    collector.last_seen_at = now - timedelta(seconds=130)
    db.commit()

    run_self_monitoring(db, settings(), now)
    run_self_monitoring(db, settings(), now + timedelta(seconds=30))
    incident = db.scalar(select(Incident).where(Incident.code == "collector_stale"))
    assert incident and incident.severity == HealthState.WARNING
    assert incident.fingerprint == fingerprint(
        environment.id, "host-1", "collector_stale", f"collector:{collector.id}"
    )
    incident_id = incident.id

    run_self_monitoring(db, settings(), now + timedelta(seconds=180))
    db.expire_all()
    incident = db.get(Incident, incident_id)
    assert incident.severity == HealthState.CRITICAL
    assert db.scalar(select(func.count()).select_from(Incident).where(
        Incident.code == "collector_stale",
        Incident.lifecycle != IncidentLifecycle.RESOLVED,
    )) == 1

    collector = db.get(type(collector), collector.id)
    collector.last_seen_at = now + timedelta(seconds=181)
    db.commit()
    run_self_monitoring(db, settings(), now + timedelta(seconds=181))
    run_self_monitoring(db, settings(), now + timedelta(seconds=211))
    assert db.get(Incident, incident_id).lifecycle == IncidentLifecycle.RESOLVED


def test_never_started_collector_and_worker_alert_after_bootstrap_grace(db):
    environment, _ = setup_monitoring(db)
    notification_target(db, environment)
    now = datetime.now(UTC)

    run_self_monitoring(db, settings(), now)
    run_self_monitoring(db, settings(), now + timedelta(seconds=130))
    run_self_monitoring(db, settings(), now + timedelta(seconds=160))

    codes = set(db.scalars(select(Incident.code).where(
        Incident.lifecycle != IncidentLifecycle.RESOLVED
    )))
    assert "collector_stale" in codes
    assert "notification_worker_stale" in codes


def test_notification_outbox_age_and_worker_recovery_use_existing_lifecycle(db):
    environment, _ = setup_monitoring(db)
    notification_target(db, environment)
    now = datetime.now(UTC)
    record_worker_heartbeat(db, now)
    event = lifecycle_event(
        db,
        environment,
        now - timedelta(seconds=700),
        NotificationDeliveryState.PENDING,
    )

    run_self_monitoring(db, settings(), now)
    run_self_monitoring(db, settings(), now + timedelta(seconds=30))
    incident = db.scalar(select(Incident).where(
        Incident.code == "notification_delivery_stale"
    ))
    assert incident and incident.severity == HealthState.WARNING

    event.delivery_state = NotificationDeliveryState.SENT
    event.sent_at = now + timedelta(seconds=31)
    record_worker_heartbeat(db, now + timedelta(seconds=31))
    run_self_monitoring(db, settings(), now + timedelta(seconds=31))
    record_worker_heartbeat(db, now + timedelta(seconds=61))
    run_self_monitoring(db, settings(), now + timedelta(seconds=61))
    assert db.get(Incident, incident.id).lifecycle == IncidentLifecycle.RESOLVED


def test_stale_notification_worker_and_failed_delivery_are_separate_incidents(db):
    environment, _ = setup_monitoring(db)
    notification_target(db, environment)
    now = datetime.now(UTC)
    record_worker_heartbeat(db, now - timedelta(seconds=80))
    lifecycle_event(
        db,
        environment,
        now - timedelta(seconds=30),
        NotificationDeliveryState.FAILED,
    )

    run_self_monitoring(db, settings(), now)
    run_self_monitoring(db, settings(), now + timedelta(seconds=30))

    incidents = list(db.scalars(select(Incident).where(
        Incident.lifecycle != IncidentLifecycle.RESOLVED,
        Incident.code.in_([
            "notification_worker_stale",
            "notification_delivery_stale",
        ]),
    )))
    assert {item.code for item in incidents} == {
        "notification_worker_stale",
        "notification_delivery_stale",
    }
    assert all(item.severity == HealthState.CRITICAL for item in incidents)


def test_newer_sent_delivery_resolves_terminal_failed_state(db):
    environment, _ = setup_monitoring(db)
    notification_target(db, environment)
    now = datetime.now(UTC)
    record_worker_heartbeat(db, now)
    lifecycle_event(
        db,
        environment,
        now - timedelta(seconds=30),
        NotificationDeliveryState.FAILED,
    )
    run_self_monitoring(db, settings(), now)
    run_self_monitoring(db, settings(), now + timedelta(seconds=30))
    delivery_incident = db.scalar(select(Incident).where(
        Incident.code == "notification_delivery_stale"
    ))
    assert delivery_incident and delivery_incident.lifecycle == IncidentLifecycle.OPEN

    lifecycle_event(
        db,
        environment,
        now + timedelta(seconds=31),
        NotificationDeliveryState.SENT,
    )
    record_worker_heartbeat(db, now + timedelta(seconds=31))
    run_self_monitoring(db, settings(), now + timedelta(seconds=31))
    record_worker_heartbeat(db, now + timedelta(seconds=61))
    run_self_monitoring(db, settings(), now + timedelta(seconds=61))

    assert db.get(Incident, delivery_incident.id).lifecycle == IncidentLifecycle.RESOLVED


def test_unconfigured_notifications_are_unknown_without_false_incident(db):
    environment, _ = setup_monitoring(db)
    notification_target(db, environment)
    now = datetime.now(UTC)
    record_worker_heartbeat(db, now)
    lifecycle_event(
        db,
        environment,
        now - timedelta(seconds=1900),
        NotificationDeliveryState.PENDING,
    )
    disabled = settings(notification_email_to="")

    run_self_monitoring(db, disabled, now)
    run_self_monitoring(db, disabled, now + timedelta(seconds=30))

    assert db.scalar(select(func.count()).select_from(Incident).where(
        Incident.code == "notification_delivery_stale"
    )) == 0
    outbox = db.scalar(select(Observation).where(
        Observation.signal == "notification.outbox.oldest_pending_age_seconds"
    ).order_by(Observation.observed_at.desc()))
    assert outbox.state == HealthState.UNKNOWN
