"""operations analyst request and result storage

Revision ID: 0007_operations_analyst
Revises: 0006_test_notification_event
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_operations_analyst"
down_revision = "0006_test_notification_event"
branch_labels = None
depends_on = None


def upgrade():
    trigger = postgresql.ENUM("OPENED", "ESCALATED", name="analysistrigger", create_type=False)
    status = postgresql.ENUM(
        "PENDING", "COMPLETED", "FAILED", "DISABLED",
        name="analysisrequeststatus", create_type=False
    )
    confidence = postgresql.ENUM("LOW", "MEDIUM", "HIGH", name="analysisconfidence",
                                 create_type=False)
    for enum in (trigger, status, confidence):
        enum.create(op.get_bind(), checkfirst=True)
    health = postgresql.ENUM("HEALTHY", "DEGRADED", "WARNING", "CRITICAL", "UNKNOWN",
                             name="healthstate", create_type=False)
    op.create_table(
        "analysis_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("trigger_event", trigger, nullable=False),
        sa.Column("trigger_severity", health, nullable=False),
        sa.Column("deduplication_key", sa.String(160), nullable=False, unique=True),
        sa.Column("status", status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("safe_error_code", sa.String(80)),
    )
    op.create_index("ix_analysis_requests_incident_id", "analysis_requests", ["incident_id"])
    op.create_index("ix_analysis_requests_status", "analysis_requests", ["status"])
    op.create_table(
        "incident_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("analysis_requests.id"), nullable=False,
                  unique=True),
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("summary", sa.String(800), nullable=False),
        sa.Column("probable_cause", sa.String(800), nullable=False),
        sa.Column("impact", sa.String(800), nullable=False),
        sa.Column("confidence", confidence, nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("recommended_checks", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_incident_analyses_request_id", "incident_analyses", ["request_id"])
    op.create_index("ix_incident_analyses_incident_id", "incident_analyses", ["incident_id"])


def downgrade():
    op.drop_table("incident_analyses")
    op.drop_table("analysis_requests")
    for name in ("analysisconfidence", "analysisrequeststatus", "analysistrigger"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
