"""support synthetic test notification events

Revision ID: 0006_test_notification_event
Revises: 0005_notification_outbox
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_test_notification_event"
down_revision = "0005_notification_outbox"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE notificationeventtype ADD VALUE IF NOT EXISTS 'TEST'")
    op.alter_column("notification_events", "incident_id", existing_type=sa.Uuid(), nullable=True)


def downgrade():
    op.execute("DELETE FROM notification_events WHERE event_type = 'TEST'")
    op.alter_column("notification_events", "incident_id", existing_type=sa.Uuid(), nullable=False)
