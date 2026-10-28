"""UAT: expert runs with blind A/B trials, ratings, turn labels and pair preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0005_uat_trials"
down_revision = "0004_enrollment_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "participants",
        sa.Column("kind", sa.String(8), nullable=False, server_default="study"),
    )
    op.add_column("participants", sa.Column("label", sa.String(32), nullable=True))
    op.add_column(
        "participants",
        sa.Column("pilot", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("participants", sa.Column("plan_seed", sa.BigInteger, nullable=True))
    for column in ("test_session", "position", "scenario", "repetition"):
        op.add_column("study_sessions", sa.Column(column, sa.Integer, nullable=True))
    op.add_column("study_sessions", sa.Column("version", sa.String(1), nullable=True))
    op.add_column(
        "study_attempts",
        sa.Column("void", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("study_attempts", sa.Column("ratings", sa.JSON, nullable=True))
    op.add_column("study_attempts", sa.Column("labels", sa.JSON, nullable=True))
    op.add_column(
        "study_attempts", sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "uat_preferences",
        sa.Column("participant_id", sa.Uuid, sa.ForeignKey("participants.id"), primary_key=True),
        sa.Column("test_session", sa.Integer, primary_key=True),
        sa.Column("scenario", sa.Integer, primary_key=True),
        sa.Column("choice", sa.String(8), nullable=False),
    )


def downgrade():
    op.drop_table("uat_preferences")
    for column in ("rated_at", "labels", "ratings", "void"):
        op.drop_column("study_attempts", column)
    for column in ("version", "repetition", "scenario", "position", "test_session"):
        op.drop_column("study_sessions", column)
    for column in ("plan_seed", "pilot", "label", "kind"):
        op.drop_column("participants", column)
