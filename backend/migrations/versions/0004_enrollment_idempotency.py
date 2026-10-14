"""Idempotency key hash for participant enrollment."""

import sqlalchemy as sa
from alembic import op

revision = "0004_enrollment_idempotency"
down_revision = "0003_study_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("participants", sa.Column("enrollment_key_hash", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_participants_enrollment_key_hash", "participants", ["enrollment_key_hash"]
    )


def downgrade():
    op.drop_constraint("uq_participants_enrollment_key_hash", "participants", type_="unique")
    op.drop_column("participants", "enrollment_key_hash")
