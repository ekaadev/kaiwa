"""UAT: mark a run as abandoned instead of deleting it."""

import sqlalchemy as sa
from alembic import op

revision = "0006_uat_abandoned"
down_revision = "0005_uat_trials"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "participants", sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("participants", "abandoned_at")
