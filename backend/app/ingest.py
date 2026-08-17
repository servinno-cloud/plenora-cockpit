import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Collector, HealthState, IngestSnapshot, Observation, Target
from .monitoring import classify, evaluate, safe_numeric, secret_matches

router = APIRouter(prefix="/ingest/v1", tags=["collector-ingest"])
ALLOWED_SIGNALS = {
    "https.reachable",
    "https.status_code",
    "https.latency_ms",
    "health.status_code",
    "tls.days_remaining",
    "backup.last_attempt_at",
    "backup.last_success_at",
    "backup.status",
    "backup.backup_id",
    "backup.database_bytes",
    "backup.media_bytes",
    "backup.checksum_verified",
    "backup.git_commit",
    "backup.success_age_seconds",
    "host.uptime_seconds",
    "host.load_1m",
    "host.load_5m",
    "host.load_15m",
    "disk.root.used_bytes",
    "disk.root.free_bytes",
    "disk.root.inode_used_percent",
    "disk.backup.used_bytes",
    "disk.backup.free_bytes",
    "disk.backup.inode_used_percent",
    "disk.root.used_percent",
    "disk.root.inodes_used_percent",
    "disk.backup.used_percent",
    "backup.directory_bytes",
    "db.reachable",
    "db.version_major",
    "db.latency_ms",
    "db.size_bytes",
    "db.connections_percent",
    "db.migration_current",
    "mail.provider_state",
    "mail.worker_running",
    "mail.queue_count",
    "mail.retryable_count",
    "mail.failed_count",
    "mail.oldest_queue_age_seconds",
    "mail.last_accepted_age_seconds",
    "service.running",
    "service.health",
    "service.restart_count",
    "service.uptime_seconds",
    "service.release_state",
    "service.started_at",
    "service.image_identifier",
    "collector.sequence",
    "collector.status",
}
TEXT_VALUES = {
    "mail.provider_state": {"configured", "missing"},
    "service.health": {"healthy", "unhealthy", "starting", "none"},
    "service.release_state": {"current", "unknown"},
    "collector.status": {"online"},
}


class ObservationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")
    signal: str
    source: Literal[
        "external_https",
        "backup_status_file",
        "host_metrics",
        "database_contract",
        "mail_contract",
        "service_boundary",
        "collector_self",
    ]
    observed_at: datetime
    state: HealthState
    code: str = Field(max_length=120)
    message: str | None = Field(default=None, max_length=240)
    value: bool | int | float | str | None = None
    unit: str | None = Field(default=None, max_length=32)

    @field_validator("signal")
    @classmethod
    def signal_allowed(cls, value: str) -> str:
        if value not in ALLOWED_SIGNALS:
            raise ValueError("signal is not allowlisted")
        return value

    @field_validator("value")
    @classmethod
    def value_is_bounded(cls, value, info):
        signal = info.data.get("signal")
        if isinstance(value, str):
            if signal in {"backup.last_attempt_at", "backup.last_success_at"}:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            elif signal == "backup.status" and value not in {"success", "failed"}:
                raise ValueError("backup status is not allowlisted")
            elif signal == "backup.backup_id" and not re.fullmatch(r"[0-9A-Za-z._-]{1,80}", value):
                raise ValueError("backup id is not safe")
            elif signal == "backup.git_commit" and not re.fullmatch(r"[0-9a-f]{7,64}", value):
                raise ValueError("git commit is not safe")
            elif signal == "service.started_at":
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            elif signal == "service.image_identifier" and not re.fullmatch(
                r"sha256:[0-9a-f]{16}", value
            ):
                raise ValueError("service image identifier is not safe")
            elif signal not in {
                "backup.last_attempt_at",
                "backup.last_success_at",
                "backup.status",
                "backup.backup_id",
                "backup.git_commit",
                "service.started_at",
                "service.image_identifier",
            } and value not in TEXT_VALUES.get(signal, set()):
                raise ValueError("text value is not allowlisted")
        return value


class SnapshotBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: Literal["snapshot.v1"] = Field(alias="schema")
    snapshot_id: uuid.UUID
    collector_id: uuid.UUID
    environment_id: uuid.UUID
    sequence: int = Field(gt=0)
    generated_at: datetime
    collector_version: str = Field(pattern=r"^[0-9A-Za-z._-]{1,32}$")
    observations: list[ObservationBody] = Field(max_length=100)


@router.post("/environments/{environment_id}/snapshots", status_code=202)
async def ingest(
    environment_id: uuid.UUID,
    body: SnapshotBody,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    if int(request.headers.get("content-length", "0")) > 262144:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Snapshot too large")
    if body.environment_id != environment_id or idempotency_key != str(body.snapshot_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envelope binding failed")
    now = datetime.now(UTC)
    generated = body.generated_at.astimezone(UTC)
    if abs(now - generated) > timedelta(minutes=5):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Snapshot timestamp outside allowed window"
        )
    existing = db.get(IngestSnapshot, body.snapshot_id)
    if existing:
        return {"status": "duplicate", "server_timestamp": now, "snapshot_id": existing.id}
    collector = db.scalar(
        select(Collector)
        .where(
            Collector.id == body.collector_id,
            Collector.environment_id == environment_id,
            Collector.active.is_(True),
        )
        .with_for_update()
    )
    token = authorization.removeprefix("Bearer ") if authorization else ""
    if not collector or not secret_matches(token, collector.secret_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid collector credentials")
    if body.sequence <= collector.last_sequence:
        raise HTTPException(status.HTTP_409_CONFLICT, "Snapshot sequence replayed")
    snap = IngestSnapshot(
        id=body.snapshot_id,
        collector_id=collector.id,
        environment_id=environment_id,
        sequence=body.sequence,
        generated_at=generated,
        observation_count=len(body.observations),
    )
    db.add(snap)
    db.flush()
    for item in body.observations:
        target = db.scalar(
            select(Target).where(Target.environment_id == environment_id, Target.key == item.target)
        )
        if not target:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown target")
        state, code = classify(item.signal, item.value, item.state)
        observation = Observation(
            snapshot_id=snap.id,
            environment_id=environment_id,
            target_id=target.id,
            component=target.component,
            signal=item.signal,
            code=code,
            state=state,
            observed_at=item.observed_at.astimezone(UTC),
            numeric_value=safe_numeric(item.value),
            text_value=item.value if isinstance(item.value, str) else None,
            unit=item.unit,
            message=item.message,
            source=item.source,
        )
        db.add(observation)
        db.flush()
        evaluate(db, observation, target.key)
    collector.last_sequence = body.sequence
    collector.last_seen_at = now
    db.commit()
    return {"status": "accepted", "server_timestamp": now, "snapshot_id": snap.id}
