"""Add demo bank relationship and new purpose codes without rewriting submissions."""

import sqlalchemy as sa
from alembic import op

revision = "0005_personal_pricing"
down_revision = "0004_draft_archive"
branch_labels = None
depends_on = None

OLD_PURPOSES = ("INVENTORY", "OPERATING_EXPENSES", "SEASONAL_PURCHASE")


def purposes(values):
    for table in ("applications", "application_revisions"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(op.f(f"ck_{table}_purpose"), type_="check")
            batch.create_check_constraint(
                op.f(f"ck_{table}_purpose"),
                "purpose_code IN (" + ", ".join(repr(v) for v in values) + ")",
            )
    if op.get_context().dialect.name == "sqlite":
        # SQLite batch rebuilds the table and drops its custom triggers.
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER revisions_immutable_{action.lower()} BEFORE {action} ON application_revisions BEGIN SELECT RAISE(ABORT, 'Submitted revisions are immutable'); END"
            )


def upgrade():
    op.add_column(
        "companies",
        sa.Column(
            "has_active_loan_in_our_bank", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    purposes((*OLD_PURPOSES, "EQUIPMENT", "OTHER"))


def downgrade():
    # Existing new-purpose rows must be explicitly handled before a downgrade.
    purposes(OLD_PURPOSES)
    op.drop_column("companies", "has_active_loan_in_our_bank")
