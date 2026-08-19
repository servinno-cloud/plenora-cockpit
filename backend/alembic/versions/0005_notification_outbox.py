"""incident notification outbox

Revision ID: 0005_notification_outbox
Revises: 0004_multiple_collectors
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_notification_outbox"
down_revision = "0004_multiple_collectors"
branch_labels = None
depends_on = None


def upgrade():
    event_type = postgresql.ENUM(
        "OPENED", "ESCALATED", "RESOLVED", name="notificationeventtype", create_type=False
    )
    delivery = postgresql.ENUM(
        "PENDING", "SENT", "FAILED", name="notificationdeliverystate", create_type=False
    )
    health = postgresql.ENUM(
        "HEALTHY", "DEGRADED", "WARNING", "CRITICAL", "UNKNOWN",
        name="healthstate", create_type=False
    )
    event_type.create(op.get_bind(), checkfirst=True)
    delivery.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("deduplication_key", sa.String(160), nullable=False),
        sa.Column("from_severity", health, nullable=True),
        sa.Column("to_severity", health, nullable=False),
        sa.Column("delivery_state", delivery, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("deduplication_key", name="uq_notification_dedup"),
    )
    op.create_index("ix_notification_events_incident_id", "notification_events", ["incident_id"])
    op.create_index(
        "ix_notification_events_delivery_state", "notification_events", ["delivery_state"]
    )


def downgrade():
    op.drop_table("notification_events")
    sa.Enum(name="notificationdeliverystate").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notificationeventtype").drop(op.get_bind(), checkfirst=True)
