"""Persist a demo signature and expose the final SIGNED application state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_demo_signing"
down_revision = "0006_scenario_sets"
branch_labels = None
depends_on = None
OLD_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "CHECKING",
    "NEEDS_INFO",
    "MANUAL_REVIEW",
    "APPROVED",
    "REJECTED",
)
OLD_EVENTS = (
    "DRAFT_CREATED",
    "SUBMITTED",
    "CHECKS_COMPLETED",
    "INFO_REQUESTED",
    "INFO_ANSWERED",
    "DECISION_MADE",
    "PROCESSING_RETRIED",
    "DRAFT_ARCHIVED",
)


def allowed(column, values):
    return column + " IN (" + ", ".join(repr(value) for value in values) + ")"


def constraints(signed):
    statuses = (*OLD_STATUSES, "SIGNED") if signed else OLD_STATUSES
    finals = ("APPROVED", "REJECTED", "SIGNED") if signed else ("APPROVED", "REJECTED")
    with op.batch_alter_table("applications") as batch:
        batch.drop_constraint(op.f("ck_applications_applicationstatus"), type_="check")
        batch.create_check_constraint(
            op.f("ck_applications_applicationstatus"), allowed("status", statuses)
        )
        batch.drop_constraint(op.f("ck_applications_final_closed_at"), type_="check")
        final = allowed("status", finals)
        batch.create_check_constraint(
            op.f("ck_applications_final_closed_at"),
            f"({final} AND closed_at IS NOT NULL) OR (NOT ({final}) AND closed_at IS NULL)",
        )
        if signed:
            batch.create_check_constraint(
                op.f("ck_applications_signing_presence"),
                "(status = 'SIGNED' AND signing_record IS NOT NULL) OR (status <> 'SIGNED' AND signing_record IS NULL)",
            )
        else:
            batch.drop_constraint(op.f("ck_applications_signing_presence"), type_="check")
    with op.batch_alter_table("application_events") as batch:
        for column in ("from_status", "to_status"):
            name = op.f("ck_application_events_" + column)
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, allowed(column, statuses))
        batch.drop_constraint(op.f("ck_application_events_eventtype"), type_="check")
        batch.create_check_constraint(
            op.f("ck_application_events_eventtype"),
            allowed("event_type", (*OLD_EVENTS, "AGREEMENT_SIGNED") if signed else OLD_EVENTS),
        )


def upgrade():
    op.add_column(
        "applications",
        sa.Column(
            "signing_record",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True), "postgresql"
            ),
            nullable=True,
        ),
    )
    constraints(True)
    if op.get_context().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION protect_demo_signature() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.signing_record IS NOT NULL AND NEW.signing_record IS DISTINCT FROM OLD.signing_record THEN
            RAISE EXCEPTION 'Demo signature is immutable' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END; $$""")
        op.execute(
            "CREATE TRIGGER demo_signature_immutable BEFORE UPDATE ON applications FOR EACH ROW EXECUTE FUNCTION protect_demo_signature()"
        )
    else:
        op.execute("""CREATE TRIGGER demo_signature_immutable BEFORE UPDATE ON applications
        WHEN OLD.signing_record IS NOT NULL AND NEW.signing_record IS NOT OLD.signing_record
        BEGIN SELECT RAISE(ABORT, 'Demo signature is immutable'); END""")


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM applications WHERE signing_record IS NOT NULL")
    ):
        raise RuntimeError(
            "Cannot downgrade with saved demo signatures; preserve signed records first"
        )
    op.execute(
        "DROP TRIGGER demo_signature_immutable"
        + (" ON applications" if op.get_context().dialect.name == "postgresql" else "")
    )
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP FUNCTION protect_demo_signature()")
    constraints(False)
    op.drop_column("applications", "signing_record")
