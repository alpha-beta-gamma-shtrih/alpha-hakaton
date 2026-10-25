"""Persist server-owned financing options without modifying submitted revisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_scenario_sets"
down_revision = "0005_personal_pricing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "applications",
        sa.Column(
            "scenario_set", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True
        ),
    )


def downgrade():
    op.drop_column("applications", "scenario_set")
