"""allow independent push and external collector identities

Revision ID: 0004_multiple_collectors
Revises: 0003_infrastructure_visibility
"""

from alembic import op

revision = "0004_multiple_collectors"
down_revision = "0003_infrastructure_visibility"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("collectors_environment_id_key", "collectors", type_="unique")
    op.create_index("ix_collectors_environment_id", "collectors", ["environment_id"])


def downgrade():
    op.drop_index("ix_collectors_environment_id", table_name="collectors")
    op.create_unique_constraint(
        "collectors_environment_id_key", "collectors", ["environment_id"]
    )
