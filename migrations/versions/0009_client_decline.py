"""Keep a client's refusal separate from the bank's immutable approval."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_client_decline"
down_revision = "0008_bank_offers"
branch_labels = None
depends_on = None
OLD_EVENTS = (
    "DRAFT_CREATED",
    "SUBMITTED",
    "CHECKS_COMPLETED",
    "INFO_REQUESTED",
    "INFO_ANSWERED",
    "DECISION_MADE",
    "PROCESSING_RETRIED",
    "DRAFT_ARCHIVED",
    "AGREEMENT_SIGNED",
)


def event_constraint(decline):
    values = (*OLD_EVENTS, "AGREEMENT_DECLINED") if decline else OLD_EVENTS
    with op.batch_alter_table("application_events") as batch:
        batch.drop_constraint(op.f("ck_application_events_eventtype"), type_="check")
        batch.create_check_constraint(
            op.f("ck_application_events_eventtype"),
            "event_type IN (" + ", ".join(repr(value) for value in values) + ")",
        )


def restore_sqlite_signature_trigger():
    # SQLite batch alterations rebuild the table, including dropping its triggers.
    op.execute("""CREATE TRIGGER demo_signature_immutable BEFORE UPDATE OF signing_record
        ON applications WHEN OLD.signing_record IS NOT NULL
        AND NEW.signing_record IS NOT OLD.signing_record
        BEGIN SELECT RAISE(ABORT, 'Demo signature is immutable'); END""")


def upgrade():
    with op.batch_alter_table("applications") as batch:
        batch.add_column(
            sa.Column(
                "decline_record",
                sa.JSON(none_as_null=True).with_variant(
                    postgresql.JSONB(none_as_null=True), "postgresql"
                ),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            op.f("ck_applications_decline_status"),
            "decline_record IS NULL OR status = 'REJECTED'",
        )
    event_constraint(True)
    if op.get_context().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION protect_client_decline() RETURNS trigger AS $$
            BEGIN
              IF OLD.decline_record IS NOT NULL
                 AND NEW.decline_record IS DISTINCT FROM OLD.decline_record THEN
                RAISE EXCEPTION 'Client refusal is immutable' USING ERRCODE = '23514';
              END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER client_decline_immutable BEFORE UPDATE OF decline_record
            ON applications FOR EACH ROW EXECUTE FUNCTION protect_client_decline()""")
    else:
        restore_sqlite_signature_trigger()
        op.execute("""CREATE TRIGGER client_decline_immutable BEFORE UPDATE OF decline_record
            ON applications WHEN OLD.decline_record IS NOT NULL
            AND NEW.decline_record IS NOT OLD.decline_record
            BEGIN SELECT RAISE(ABORT, 'Client refusal is immutable'); END""")


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM applications WHERE decline_record IS NOT NULL")
    ):
        raise RuntimeError("Cannot discard saved client refusals; preserve them before downgrade")
    pg = op.get_context().dialect.name == "postgresql"
    op.execute("DROP TRIGGER client_decline_immutable" + (" ON applications" if pg else ""))
    if pg:
        op.execute("DROP FUNCTION protect_client_decline()")
    event_constraint(False)
    with op.batch_alter_table("applications") as batch:
        batch.drop_constraint(op.f("ck_applications_decline_status"), type_="check")
        batch.drop_column("decline_record")
    if not pg:
        restore_sqlite_signature_trigger()
