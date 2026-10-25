"""Preserve a bank's changed terms separately from the submitted application."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_bank_offers"
down_revision = "0007_demo_signing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "decisions",
        sa.Column(
            "offer_snapshot",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True), "postgresql"
            ),
            nullable=True,
        ),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM decisions WHERE offer_snapshot IS NOT NULL")
    ):
        raise RuntimeError("Cannot discard saved bank offers; preserve them before downgrade")
    op.drop_column("decisions", "offer_snapshot")
