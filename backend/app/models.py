import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class HealthState(enum.StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class IncidentLifecycle(enum.StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class NotificationEventType(enum.StrEnum):
    OPENED = "OPENED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    TEST = "TEST"


class NotificationDeliveryState(enum.StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class AnalysisTrigger(enum.StrEnum):
    OPENED = "OPENED"
    ESCALATED = "ESCALATED"
    TEST = "TEST"


class AnalysisRequestStatus(enum.StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


class AnalysisConfidence(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OperatorRole(enum.StrEnum):
    OWNER = "OWNER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    environments: Mapped[list["Environment"]] = relationship(back_populates="product")


class Environment(TimestampMixin, Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("product_id", "code", name="uq_environment_code"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    product: Mapped[Product] = relationship(back_populates="environments")
    targets: Mapped[list["Target"]] = relationship(back_populates="environment")


class Collector(Base):
    __tablename__ = "collectors"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    secret_hash: Mapped[str] = mapped_column(String(64))
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class IngestSnapshot(Base):
    __tablename__ = "ingest_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    collector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collectors.id"))
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    observation_count: Mapped[int] = mapped_column(Integer)


class Target(TimestampMixin, Base):
    __tablename__ = "targets"
    __table_args__ = (UniqueConstraint("environment_id", "key", name="uq_target_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    component: Mapped[str] = mapped_column(String(80))
    environment: Mapped[Environment] = relationship(back_populates="targets")


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observation_environment_observed", "environment_id", "observed_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingest_snapshots.id"))
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id"))
    target_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("targets.id"))
    component: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(120))
    signal: Mapped[str] = mapped_column(String(120), default="unknown")
    state: Mapped[HealthState] = mapped_column(Enum(HealthState))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    text_value: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(String(240))
    source: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incident_environment_state", "environment_id", "lifecycle"),
        Index(
            "uq_active_incident_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text("lifecycle != 'RESOLVED'"),
            sqlite_where=text("lifecycle != 'RESOLVED'"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id"))
    target_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("targets.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[HealthState] = mapped_column(Enum(HealthState))
    lifecycle: Mapped[IncidentLifecycle] = mapped_column(Enum(IncidentLifecycle))
    source: Mapped[str] = mapped_column(String(80))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    latest_observation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("observations.id"))
    policy_version: Mapped[str] = mapped_column(String(32), default="sprint1.v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (UniqueConstraint("deduplication_key", name="uq_notification_dedup"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    event_type: Mapped[NotificationEventType] = mapped_column(Enum(NotificationEventType))
    deduplication_key: Mapped[str] = mapped_column(String(160))
    from_severity: Mapped[HealthState | None] = mapped_column(Enum(HealthState))
    to_severity: Mapped[HealthState] = mapped_column(Enum(HealthState))
    delivery_state: Mapped[NotificationDeliveryState] = mapped_column(
        Enum(NotificationDeliveryState), default=NotificationDeliveryState.PENDING, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    incident: Mapped[Incident | None] = relationship()


class AnalysisRequest(Base):
    __tablename__ = "analysis_requests"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    trigger_event: Mapped[AnalysisTrigger] = mapped_column(Enum(AnalysisTrigger))
    trigger_severity: Mapped[HealthState] = mapped_column(Enum(HealthState))
    deduplication_key: Mapped[str] = mapped_column(String(160), unique=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    test_context: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[AnalysisRequestStatus] = mapped_column(
        Enum(AnalysisRequestStatus), default=AnalysisRequestStatus.PENDING, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    incident: Mapped[Incident | None] = relationship()


class IncidentAnalysis(Base):
    __tablename__ = "incident_analyses"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_requests.id"), unique=True, index=True
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    summary: Mapped[str] = mapped_column(String(800))
    probable_cause: Mapped[str] = mapped_column(String(800))
    impact: Mapped[str] = mapped_column(String(800))
    confidence: Mapped[AnalysisConfidence] = mapped_column(Enum(AnalysisConfidence))
    evidence: Mapped[list[str]] = mapped_column(JSON)
    recommended_checks: Mapped[list[str]] = mapped_column(JSON)
    limitations: Mapped[list[str]] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request: Mapped[AnalysisRequest] = relationship()


class AIUsage(Base):
    __tablename__ = "ai_usage"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_key: Mapped[str] = mapped_column(String(80), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_requests.id"), unique=True, index=True
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    reserved_cost_eur: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    pricing_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIMonthlyBudget(Base):
    __tablename__ = "ai_monthly_budgets"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    spent_eur: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal("0"))
    reserved_eur: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Operator(TimestampMixin, Base):
    __tablename__ = "operators"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[OperatorRole] = mapped_column(Enum(OperatorRole))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperatorSession(Base):
    __tablename__ = "operator_sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operators.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    operator: Mapped[Operator] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operators.id"))
    action: Mapped[str] = mapped_column(String(80))
    success: Mapped[bool] = mapped_column(Boolean)
    subject_hash: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64))
    source_ip_prefix: Mapped[str | None] = mapped_column(String(64))
    detail_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    operator: Mapped[Operator | None] = relationship()
