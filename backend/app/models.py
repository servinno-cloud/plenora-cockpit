import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
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
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id"))
    target_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("targets.id"))
    component: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(120))
    state: Mapped[HealthState] = mapped_column(Enum(HealthState))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    unit: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(String(240))
    source: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incident_environment_state", "environment_id", "lifecycle"),)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
