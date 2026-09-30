"""References to final private study evidence manifests."""

import sqlalchemy as sa
from alembic import op

revision = "0003_study_evidence"
down_revision = "0002_study_attempts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "study_evidence",
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("study_attempts.id"), primary_key=True),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    op.drop_table("study_evidence")
