from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    Collector,
    HealthState,
    Incident,
    IngestSnapshot,
    NotificationDeliveryState,
    NotificationEvent,
    Observation,
    Target,
)
from .monitoring import evaluate


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    return max(0, int((_utc(now) - _utc(value)).total_seconds())) if value else None


def _freshness_state(age: int | None, warning: int, critical: int) -> HealthState:
    if age is None:
        return HealthState.UNKNOWN
    if age > critical:
        return HealthState.CRITICAL
    if age > warning:
        return HealthState.WARNING
    return HealthState.HEALTHY


def _missing_source_state(
    db: Session,
    target: Target,
    signal: str,
    component: str,
    now: datetime,
    warning: int,
    critical: int,
) -> tuple[int | None, HealthState]:
    first_check = db.scalar(
        select(func.min(Observation.observed_at)).where(
            Observation.target_id == target.id,
            Observation.signal == signal,
            Observation.component == component,
        )
    )
    age = _age_seconds(now, first_check)
    if age is None or age <= warning:
        return age, HealthState.UNKNOWN
    return age, _freshness_state(age, warning, critical)


def _add_observation(
    db: Session,
    target: Target,
    signal: str,
    state: HealthState,
    now: datetime,
    value: int | None = None,
    message: str | None = None,
    fingerprint_target: str | None = None,
    component: str | None = None,
) -> Observation:
    observation = Observation(
        snapshot_id=None,
        environment_id=target.environment_id,
        target_id=target.id,
        component=component or target.component,
        signal=signal,
        code="ok" if state == HealthState.HEALTHY else "self_monitoring_threshold",
        state=state,
        observed_at=now,
        numeric_value=value,
        text_value=None,
        unit="s" if value is not None else None,
        message=message,
        source="cockpit_self",
    )
    db.add(observation)
    db.flush()
    evaluate(db, observation, fingerprint_target or target.key)
    return observation


def _collector_target(db: Session, collector: Collector) -> Target | None:
    target = db.scalar(
        select(Target)
        .join(Observation, Observation.target_id == Target.id)
        .join(IngestSnapshot, IngestSnapshot.id == Observation.snapshot_id)
        .where(
            IngestSnapshot.collector_id == collector.id,
            Observation.signal == "collector.status",
        )
        .order_by(Observation.observed_at.desc())
        .limit(1)
    )
    if target:
        return target
    fallback = "observer" if "observer" in collector.name.casefold() else "collector"
    return db.scalar(
        select(Target).where(
            Target.environment_id == collector.environment_id,
            Target.key == fallback,
        )
    )


def collector_inventory(
    db: Session, settings: Settings, now: datetime | None = None
) -> list[dict[str, object]]:
    checked_at = now or datetime.now(UTC)
    result = []
    for collector in db.scalars(select(Collector).where(Collector.active.is_(True))):
        latest_observation = db.scalar(
            select(func.max(Observation.observed_at))
            .join(IngestSnapshot, IngestSnapshot.id == Observation.snapshot_id)
            .where(IngestSnapshot.collector_id == collector.id)
        )
        age = _age_seconds(checked_at, collector.last_seen_at)
        status = _freshness_state(
            age,
            settings.collector_freshness_warning_seconds,
            settings.collector_freshness_critical_seconds,
        )
        if collector.last_seen_at is None:
            latest_check = db.scalar(
                select(Observation)
                .where(
                    Observation.environment_id == collector.environment_id,
                    Observation.signal == "collector.freshness_seconds",
                    Observation.component == collector.name[:80],
                )
                .order_by(Observation.observed_at.desc())
                .limit(1)
            )
            status = latest_check.state if latest_check else HealthState.UNKNOWN
        result.append(
            {
                "id": collector.id,
                "name": collector.name,
                "last_successful_run_at": collector.last_seen_at,
                "last_observation_at": latest_observation,
                "last_snapshot_age_seconds": age,
                "expected_interval_seconds": settings.collector_expected_interval_seconds,
                "maximum_age_seconds": settings.collector_freshness_critical_seconds,
                "status": status.value,
                "state_storage": "postgresql.collectors+ingest_snapshots+observations",
            }
        )
    return result


def evaluate_collectors(db: Session, settings: Settings, now: datetime) -> int:
    count = 0
    for collector in db.scalars(select(Collector).where(Collector.active.is_(True))):
        target = _collector_target(db, collector)
        if not target:
            continue
        age = _age_seconds(now, collector.last_seen_at)
        if collector.last_seen_at is None:
            age, state = _missing_source_state(
                db,
                target,
                "collector.freshness_seconds",
                collector.name[:80],
                now,
                settings.collector_freshness_warning_seconds,
                settings.collector_freshness_critical_seconds,
            )
        else:
            state = _freshness_state(
                age,
                settings.collector_freshness_warning_seconds,
                settings.collector_freshness_critical_seconds,
            )
        _add_observation(
            db,
            target,
            "collector.freshness_seconds",
            state,
            now,
            age,
            "Collector freshness gecontroleerd",
            f"{target.key}:{collector.id}",
            collector.name[:80],
        )
        count += 1
    return count


def evaluate_notifications(db: Session, settings: Settings, now: datetime) -> int:
    count = 0
    targets = list(db.scalars(select(Target).where(Target.key == "cockpit-notifications")))
    for target in targets:
        heartbeat_at = db.scalar(
            select(func.max(Observation.observed_at)).where(
                Observation.environment_id == target.environment_id,
                Observation.signal == "notification.worker_heartbeat",
            )
        )
        heartbeat_age = _age_seconds(now, heartbeat_at)
        if heartbeat_at is None:
            heartbeat_age, heartbeat_state = _missing_source_state(
                db,
                target,
                "notification.worker_freshness_seconds",
                target.component,
                now,
                settings.notification_worker_warning_seconds,
                settings.notification_worker_critical_seconds,
            )
        else:
            heartbeat_state = _freshness_state(
                heartbeat_age,
                settings.notification_worker_warning_seconds,
                settings.notification_worker_critical_seconds,
            )
        _add_observation(
            db,
            target,
            "notification.worker_freshness_seconds",
            heartbeat_state,
            now,
            heartbeat_age,
            "Notificatieworker freshness gecontroleerd",
        )

        oldest_pending = db.scalar(
            select(func.min(NotificationEvent.created_at))
            .join(Incident, Incident.id == NotificationEvent.incident_id)
            .where(
                Incident.environment_id == target.environment_id,
                NotificationEvent.delivery_state == NotificationDeliveryState.PENDING,
            )
        )
        pending_age = _age_seconds(now, oldest_pending) or 0
        pending_state = (
            _freshness_state(
                pending_age,
                settings.notification_outbox_warning_seconds,
                settings.notification_outbox_critical_seconds,
            )
            if settings.notifications_configured
            else HealthState.UNKNOWN
        )
        _add_observation(
            db,
            target,
            "notification.outbox.oldest_pending_age_seconds",
            pending_state,
            now,
            pending_age,
            "Notificatie-outbox freshness gecontroleerd",
        )

        latest_terminal = db.scalar(
            select(NotificationEvent)
            .join(Incident, Incident.id == NotificationEvent.incident_id)
            .where(
                Incident.environment_id == target.environment_id,
                NotificationEvent.delivery_state.in_(
                    [NotificationDeliveryState.SENT, NotificationDeliveryState.FAILED]
                ),
            )
            .order_by(NotificationEvent.created_at.desc())
            .limit(1)
        )
        delivery_state = HealthState.UNKNOWN
        if latest_terminal and settings.notifications_configured:
            delivery_state = (
                HealthState.HEALTHY
                if latest_terminal.delivery_state == NotificationDeliveryState.SENT
                else HealthState.CRITICAL
            )
        _add_observation(
            db,
            target,
            "notification.delivery_health",
            delivery_state,
            now,
            message="Laatste terminale notificatielevering gecontroleerd",
        )
        count += 3
    return count


def run_self_monitoring(
    db: Session, settings: Settings, now: datetime | None = None
) -> int:
    checked_at = now or datetime.now(UTC)
    count = evaluate_collectors(db, settings, checked_at)
    count += evaluate_notifications(db, settings, checked_at)
    db.commit()
    return count
