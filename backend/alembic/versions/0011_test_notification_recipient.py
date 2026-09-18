"""add one-shot test notification recipient

Revision ID: 0011_test_notification_recipient
Revises: 0010_safe_analysis_test_harness
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_test_notification_recipient"
down_revision = "0010_safe_analysis_test_harness"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_events",
        sa.Column("test_recipient", sa.String(length=254), nullable=True),
    )


def downgrade():
    op.drop_column("notification_events", "test_recipient")
