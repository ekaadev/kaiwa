"""Record every study call attempt without replacing previous outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "0002_study_attempts"
down_revision = "0001_study_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "study_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("study_sessions.id"), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("media_ms", sa.Integer(), nullable=False),
        sa.Column("end_reason", sa.String(32)),
        sa.Column("evidence_saved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "request_hash"),
    )
    op.create_index("ix_study_attempts_session_id", "study_attempts", ["session_id"])
    op.create_index(
        "one_active_attempt_per_session",
        "study_attempts",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('starting', 'active', 'awaiting_evidence')"),
        sqlite_where=sa.text("status IN ('starting', 'active', 'awaiting_evidence')"),
    )


def downgrade():
    op.drop_index("one_active_attempt_per_session", table_name="study_attempts")
    op.drop_index("ix_study_attempts_session_id", table_name="study_attempts")
    op.drop_table("study_attempts")
