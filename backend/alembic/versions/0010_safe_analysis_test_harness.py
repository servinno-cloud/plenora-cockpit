"""safe operations analyst test harness

Revision ID: 0010_safe_analysis_test_harness
Revises: 0009_cache_write_accounting
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_safe_analysis_test_harness"
down_revision = "0009_cache_write_accounting"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE analysistrigger ADD VALUE IF NOT EXISTS 'TEST'")
    op.add_column(
        "analysis_requests",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("analysis_requests", sa.Column("test_context", sa.JSON(), nullable=True))
    op.alter_column("analysis_requests", "incident_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("incident_analyses", "incident_id", existing_type=sa.Uuid(), nullable=True)


def downgrade():
    op.execute("DELETE FROM incident_analyses WHERE incident_id IS NULL")
    op.execute(
        "UPDATE ai_usage SET request_id = NULL WHERE request_id IN "
        "(SELECT id FROM analysis_requests WHERE incident_id IS NULL)"
    )
    op.execute("DELETE FROM analysis_requests WHERE incident_id IS NULL")
    op.alter_column("incident_analyses", "incident_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("analysis_requests", "incident_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("analysis_requests", "test_context")
    op.drop_column("analysis_requests", "is_test")
