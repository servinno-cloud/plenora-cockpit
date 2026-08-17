"""infrastructure visibility values

Revision ID: 0003_infrastructure_visibility
Revises: 0002_real_monitoring
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_infrastructure_visibility"
down_revision = "0002_real_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("observations", sa.Column("text_value", sa.String(80), nullable=True))


def downgrade():
    op.drop_column("observations", "text_value")
