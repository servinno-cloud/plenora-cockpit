"""AI usage accounting and monthly reservations

Revision ID: 0008_ai_usage_budget
Revises: 0007_operations_analyst
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_ai_usage_budget"
down_revision = "0007_operations_analyst"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_monthly_budgets",
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("spent_eur", sa.Numeric(20, 10), nullable=False, server_default="0"),
        sa.Column("reserved_eur", sa.Numeric(20, 10), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_key", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("analysis_requests.id"),
                  nullable=False, unique=True),
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id")),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("cached_input_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("estimated_cost_eur", sa.Numeric(20, 10)),
        sa.Column("reserved_cost_eur", sa.Numeric(20, 10), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("pricing_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_usage_agent_key", "ai_usage", ["agent_key"])
    op.create_index("ix_ai_usage_request_id", "ai_usage", ["request_id"])
    op.create_index("ix_ai_usage_incident_id", "ai_usage", ["incident_id"])
    op.create_index("ix_ai_usage_status", "ai_usage", ["status"])


def downgrade():
    op.drop_table("ai_usage")
    op.drop_table("ai_monthly_budgets")
