"""real monitoring; Revision ID: 0002_real_monitoring; Revises: 0001_foundation"""

import sqlalchemy as sa

from alembic import op

revision = "0002_real_monitoring"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collectors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "environment_id",
            sa.Uuid(),
            sa.ForeignKey("environments.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "ingest_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("collector_id", sa.Uuid(), sa.ForeignKey("collectors.id"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("observation_count", sa.Integer(), nullable=False),
    )
    op.add_column(
        "observations", sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("ingest_snapshots.id"))
    )
    op.add_column(
        "observations",
        sa.Column("signal", sa.String(120), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "incidents", sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "incidents", sa.Column("latest_observation_id", sa.Uuid(), sa.ForeignKey("observations.id"))
    )
    op.add_column(
        "incidents",
        sa.Column("policy_version", sa.String(32), nullable=False, server_default="sprint1.v1"),
    )
    op.create_index(
        "uq_active_incident_fingerprint",
        "incidents",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("lifecycle != 'RESOLVED'"),
    )


def downgrade():
    op.drop_index("uq_active_incident_fingerprint", table_name="incidents")
    for column in ("policy_version", "latest_observation_id", "occurrence_count"):
        op.drop_column("incidents", column)
    op.drop_column("observations", "signal")
    op.drop_column("observations", "snapshot_id")
    op.drop_table("ingest_snapshots")
    op.drop_table("collectors")
