"""Existing enrollment schema (baseline for deployments with pre-existing tables)."""

import sqlalchemy as sa
from alembic import op

revision = "0001_study_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "allocation_counter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fixed_first", sa.Integer(), nullable=False),
        sa.Column("adaptive_first", sa.Integer(), nullable=False),
    )
    op.create_table(
        "participants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("order", sa.String(2), nullable=False),
        sa.Column("consent_version", sa.String(64), nullable=False),
        sa.Column(
            "consented_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_participants_token_hash", "participants", ["token_hash"], unique=True)
    op.create_table(
        "study_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("participant_id", sa.Uuid(), sa.ForeignKey("participants.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.UniqueConstraint("participant_id", "ordinal"),
    )
    op.create_index("ix_study_sessions_participant_id", "study_sessions", ["participant_id"])
    op.execute(
        sa.text("INSERT INTO allocation_counter (id, fixed_first, adaptive_first) VALUES (1, 0, 0)")
    )


def downgrade():
    op.drop_index("ix_study_sessions_participant_id", table_name="study_sessions")
    op.drop_table("study_sessions")
    op.drop_index("ix_participants_token_hash", table_name="participants")
    op.drop_table("participants")
    op.drop_table("allocation_counter")
