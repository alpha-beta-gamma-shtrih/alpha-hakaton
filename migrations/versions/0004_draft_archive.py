"""Hide never-submitted drafts without deleting their attachments or history."""

import sqlalchemy as sa
from alembic import op

from credit_cabinet.db.base import UTCDateTime

revision = "0004_draft_archive"
down_revision = "0003_document_immutability"
branch_labels = None
depends_on = None

PREVIOUS_EVENTS = (
    "DRAFT_CREATED",
    "SUBMITTED",
    "CHECKS_COMPLETED",
    "INFO_REQUESTED",
    "INFO_ANSWERED",
    "DECISION_MADE",
    "PROCESSING_RETRIED",
)


def event_constraint(values):
    with op.batch_alter_table("application_events") as batch:
        batch.drop_constraint(op.f("ck_application_events_eventtype"), type_="check")
        allowed = ", ".join(f"'{value}'" for value in values)
        batch.create_check_constraint(
            op.f("ck_application_events_eventtype"), f"event_type IN ({allowed})"
        )


def upgrade():
    op.add_column("applications", sa.Column("archived_at", UTCDateTime(), nullable=True))
    event_constraint((*PREVIOUS_EVENTS, "DRAFT_ARCHIVED"))


def downgrade():
    event_constraint(PREVIOUS_EVENTS)
    op.drop_column("applications", "archived_at")
