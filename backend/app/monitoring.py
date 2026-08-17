import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import HealthState, Incident, IncidentLifecycle, Observation

FAILURE_STATES = {HealthState.DEGRADED, HealthState.WARNING, HealthState.CRITICAL}
TITLES = {
    "web_unhealthy": "Web endpoint is niet gezond",
    "backup_unhealthy": "Backupstatus vereist aandacht",
    "host_capacity": "Hostcapaciteit vereist aandacht",
    "db_unreachable": "Database is niet bereikbaar",
    "db_performance": "Databaseprestaties vereisen aandacht",
    "db_connections": "Databaseverbindingen vereisen aandacht",
    "db_migration_mismatch": "Databasemigratie wijkt af",
    "mail_worker_down": "Mailworker is niet gezond",
    "mail_delivery_risk": "Mailqueue vereist aandacht",
    "mail_provider_missing": "Mailprovider ontbreekt",
    "service_unhealthy": "Service is niet gezond",
}


def fingerprint(environment_id: uuid.UUID, component: str, code: str, target: str) -> str:
    raw = f"{environment_id}|{component}|{code}|{target}".encode()
    return hashlib.sha256(raw).hexdigest()


def classify(
    signal: str, value: bool | int | float | str | None, source_state: HealthState
) -> tuple[HealthState, str]:
    if source_state == HealthState.UNKNOWN or value is None:
        return HealthState.UNKNOWN, "signal_unknown"
    if signal in {"https.reachable", "backup.checksum_verified"}:
        if value is True:
            return HealthState.HEALTHY, "ok"
        code = "web_unhealthy" if signal.startswith("https") else "backup_unhealthy"
        return HealthState.CRITICAL, code
    if signal in {"https.status_code", "health.status_code"}:
        ok = 200 <= int(value) < 300 if signal == "https.status_code" else int(value) == 200
        return (HealthState.HEALTHY, "ok") if ok else (HealthState.CRITICAL, "web_unhealthy")
    if signal == "https.latency_ms":
        if float(value) > 2000:
            return HealthState.CRITICAL, "web_unhealthy"
        if float(value) > 500:
            return HealthState.WARNING, "web_unhealthy"
        return HealthState.HEALTHY, "ok"
    if signal == "tls.days_remaining":
        if float(value) < 14:
            return HealthState.CRITICAL, "web_unhealthy"
        if float(value) < 30:
            return HealthState.WARNING, "web_unhealthy"
        return HealthState.HEALTHY, "ok"
    if signal == "backup.status":
        return (
            (HealthState.HEALTHY, "ok")
            if value == "success"
            else (HealthState.WARNING, "backup_unhealthy")
        )
    if signal == "backup.success_age_seconds":
        if float(value) > 172800:
            return HealthState.CRITICAL, "backup_unhealthy"
        if float(value) > 93600:
            return HealthState.WARNING, "backup_unhealthy"
        return HealthState.HEALTHY, "ok"
    if signal in {
        "disk.root.used_percent",
        "disk.root.inodes_used_percent",
        "disk.backup.used_percent",
    }:
        if float(value) > 90:
            return HealthState.CRITICAL, "host_capacity"
        if float(value) > 80:
            return HealthState.WARNING, "host_capacity"
        return HealthState.HEALTHY, "ok"
    return source_state, "ok" if source_state == HealthState.HEALTHY else "signal_unknown"


def incident_code(signal: str) -> str | None:
    if signal.startswith(("https.", "health.", "tls.")):
        return "web_unhealthy"
    if signal.startswith("backup."):
        return "backup_unhealthy"
    if signal.startswith("disk."):
        return "host_capacity"
    if signal == "db.reachable":
        return "db_unreachable"
    if signal == "db.latency_ms":
        return "db_performance"
    if signal == "db.connections_percent":
        return "db_connections"
    if signal == "db.migration_current":
        return "db_migration_mismatch"
    if signal == "mail.worker_running":
        return "mail_worker_down"
    if signal == "mail.provider_state":
        return "mail_provider_missing"
    if signal.startswith("mail."):
        return "mail_delivery_risk"
    if signal.startswith("service."):
        return "service_unhealthy"
    return None


def _recent(db: Session, observation: Observation, limit: int = 2) -> list[Observation]:
    return list(
        db.scalars(
            select(Observation)
            .where(
                Observation.environment_id == observation.environment_id,
                Observation.target_id == observation.target_id,
                Observation.signal == observation.signal,
            )
            .order_by(Observation.observed_at.desc(), Observation.id.desc())
            .limit(limit)
        )
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate(db: Session, observation: Observation, target_key: str) -> None:
    code = incident_code(observation.signal)
    if code is None or observation.state == HealthState.UNKNOWN:
        return
    fp = fingerprint(observation.environment_id, observation.component, code, target_key)
    active = db.scalar(
        select(Incident).where(
            Incident.fingerprint == fp,
            Incident.lifecycle != IncidentLifecycle.RESOLVED,
        )
    )
    recent = _recent(db, observation)
    if observation.state in FAILURE_STATES:
        if active:
            active.last_seen_at = observation.observed_at
            if observation.state.value != active.severity.value:
                active.severity = observation.state
            active.occurrence_count += 1
            active.latest_observation_id = observation.id
        elif len(recent) == 2 and all(item.state in FAILURE_STATES for item in recent):
            first = min(_utc(item.observed_at) for item in recent)
            db.add(
                Incident(
                    environment_id=observation.environment_id,
                    target_id=observation.target_id,
                    fingerprint=fp,
                    component=observation.component,
                    code=code,
                    title=TITLES[code],
                    severity=observation.state,
                    lifecycle=IncidentLifecycle.OPEN,
                    source=observation.source,
                    first_seen_at=first,
                    last_seen_at=observation.observed_at,
                    latest_observation_id=observation.id,
                    occurrence_count=2,
                    policy_version="sprint1.v1",
                )
            )
    elif active and len(recent) == 2 and all(item.state == HealthState.HEALTHY for item in recent):
        active.lifecycle = IncidentLifecycle.RESOLVED
        active.resolved_at = observation.observed_at
        active.latest_observation_id = observation.id


def safe_numeric(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def secret_matches(raw: str, stored: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), stored)
