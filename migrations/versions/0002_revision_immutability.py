"""Protect submitted snapshots from UPDATE/DELETE, including direct SQL.

Revision ID: 0002_revision_immutability
Revises: 0001_demo_02
"""

from alembic import op

revision = "0002_revision_immutability"
down_revision = "0001_demo_02"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_revision_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Submitted revisions are immutable' USING ERRCODE = '23514';
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER revisions_immutable
            BEFORE UPDATE OR DELETE ON application_revisions
            FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation()
        """)
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""
                CREATE TRIGGER revisions_immutable_{action.lower()}
                BEFORE {action} ON application_revisions
                BEGIN SELECT RAISE(ABORT, 'Submitted revisions are immutable'); END
            """)


def downgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP TRIGGER revisions_immutable ON application_revisions")
        op.execute("DROP FUNCTION reject_revision_mutation()")
    else:
        op.execute("DROP TRIGGER revisions_immutable_update")
        op.execute("DROP TRIGGER revisions_immutable_delete")
