"""Cockpit Sprint 0 foundation.

Revision ID: 0001_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

health = sa.Enum("HEALTHY", "DEGRADED", "WARNING", "CRITICAL", "UNKNOWN", name="healthstate")
lifecycle = sa.Enum("OPEN", "ACKNOWLEDGED", "RESOLVED", name="incidentlifecycle")
role = sa.Enum("OWNER", "OPERATOR", "VIEWER", name="operatorrole")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "operators",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", role, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_table(
        "environments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("product_id", "code", name="uq_environment_code"),
    )
    op.create_table(
        "targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("component", sa.String(80), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("environment_id", "key", name="uq_target_key"),
    )
    op.create_table(
        "operator_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("operator_id", sa.Uuid(), sa.ForeignKey("operators.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("targets.id")),
        sa.Column("component", sa.String(80), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("state", health, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("numeric_value", sa.Numeric(20, 4)),
        sa.Column("unit", sa.String(32)),
        sa.Column("message", sa.String(240)),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_observation_environment_observed", "observations", ["environment_id", "observed_at"]
    )
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("targets.id")),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("component", sa.String(80), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("severity", health, nullable=False),
        sa.Column("lifecycle", lifecycle, nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_incidents_fingerprint", "incidents", ["fingerprint"])
    op.create_index("ix_incident_environment_state", "incidents", ["environment_id", "lifecycle"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("operator_id", sa.Uuid(), sa.ForeignKey("operators.id")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("subject_hash", sa.String(64)),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("source_ip_prefix", sa.String(64)),
        sa.Column("detail_code", sa.String(80)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    for table in (
        "audit_events",
        "incidents",
        "observations",
        "operator_sessions",
        "targets",
        "environments",
        "operators",
        "products",
    ):
        op.drop_table(table)
    lifecycle.drop(op.get_bind(), checkfirst=True)
    health.drop(op.get_bind(), checkfirst=True)
    role.drop(op.get_bind(), checkfirst=True)
