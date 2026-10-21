"""Prevent replacing document metadata referenced by immutable revisions."""

from alembic import op

revision = "0003_document_immutability"
down_revision = "0002_revision_immutability"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_document_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Documents are immutable' USING ERRCODE = '23514';
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER documents_immutable
            BEFORE UPDATE OR DELETE ON documents
            FOR EACH ROW EXECUTE FUNCTION reject_document_mutation()
        """)
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""
                CREATE TRIGGER documents_immutable_{action.lower()}
                BEFORE {action} ON documents
                BEGIN SELECT RAISE(ABORT, 'Documents are immutable'); END
            """)


def downgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP TRIGGER documents_immutable ON documents")
        op.execute("DROP FUNCTION reject_document_mutation()")
    else:
        op.execute("DROP TRIGGER documents_immutable_update")
        op.execute("DROP TRIGGER documents_immutable_delete")
