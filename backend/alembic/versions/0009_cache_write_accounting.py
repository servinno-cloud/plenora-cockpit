"""GPT-5.6 cache-write token accounting

Revision ID: 0009_cache_write_accounting
Revises: 0008_ai_usage_budget
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_cache_write_accounting"
down_revision = "0008_ai_usage_budget"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ai_usage",
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("ai_usage", "cache_write_tokens")
