from datetime import date
from decimal import Decimal
from io import StringIO
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm.exc import StaleDataError

from credit_cabinet.core.security import utc_now
from credit_cabinet.db.base import Base
from credit_cabinet.models import (
    Application,
    ApplicationRevision,
    Assessment,
    CheckResult,
    Company,
    CompanyFinancialMonth,
    CompanyMembership,
    CreditProduct,
    Decision,
    InformationRequest,
    User,
)
from tests.conftest import ROOT


def business_rows(db):
    user = db.scalar(select(User).where(User.email == "client@example.com"))
    company = Company(
        legal_name="DEMO Company",
        legal_form="OOO",
        inn="0000000001",
        registered_on=date(2022, 1, 1),
        okved_code="47.11",
        region_code="77",
    )
    product = CreditProduct(
        code="WC_DEMO",
        version=2,
        name="DEMO",
        description="Test only",
        allowed_purposes=["INVENTORY"],
        min_amount=Decimal("100000.00"),
        max_amount=Decimal("5000000.00"),
        min_term_months=6,
        max_term_months=24,
        annual_rate_percent=Decimal("24.000"),
        policy_version="demo-policy-0.2",
        policy_config={},
    )
    db.add_all([company, product])
    db.flush()
    applications = [
        Application(
            company_id=company.id,
            created_by_user_id=user.id,
            product_id=product.id,
            calculation_date=date(2026, 10, 1),
        )
        for _ in range(2)
    ]
    db.add_all(applications)
    db.flush()
    return user, company, applications


def revision(db, application, user):
    row = ApplicationRevision(
        application_id=application.id,
        revision_no=1,
        submitted_by_user_id=user.id,
        source_lock_version=1,
        submission_key=uuid4(),
        input_hash="a" * 64,
        requested_amount=Decimal("1000000.00"),
        term_months=12,
        purpose_code="INVENTORY",
        company_snapshot={},
        financial_snapshot={
            "confirmations": {
                "data_confirmed": True,
                "credit_history_check_allowed": True,
            }
        },
        product_snapshot={},
        document_refs=[],
        schema_version=2,
    )
    db.add(row)
    db.flush()
    return row


def assessment(db, rev):
    now = utc_now()
    row = Assessment(
        revision_id=rev.id,
        run_no=1,
        rules_version="demo-policy-0.2",
        input_facts={},
        risk_score=10,
        risk_band="LOW",
        routing="APPROVE",
        reason_codes=[],
        calculation_details={},
        started_at=now,
        completed_at=now,
    )
    db.add(row)
    db.flush()
    return row


def test_migration_has_fifteen_tables_and_no_model_drift(app):
    with app.state.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert tables == set(Base.metadata.tables) | {"alembic_version"}
        assert len(Base.metadata.tables) == 15
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []


def test_unique_and_index_names_do_not_collide():
    # PostgreSQL creates backing relations for UNIQUE/PK constraints; SQLite accepts
    # duplicate names that PostgreSQL rejects. Distinct composite keys need distinct names.
    from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint

    names = []
    for table in Base.metadata.tables.values():
        names.extend(index.name for index in table.indexes)
        names.extend(
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, (UniqueConstraint, PrimaryKeyConstraint))
        )
    assert len(names) == len(set(names))


def test_postgresql_offline_ddl_is_native_and_self_contained():
    output = StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    config.attributes["database_url"] = "postgresql+psycopg://unused@localhost/unused"
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "JSONB" in sql and "TIMESTAMP WITH TIME ZONE" in sql and "UUID" in sql
    assert sql.count("CREATE TABLE") == 16
    assert "EXTRACT(day FROM month)" in sql
    assert "WHERE status = 'OPEN'" in sql
    assert "FOREIGN KEY(assessment_id, revision_id)" in sql
    assert "NUMERIC(18, 2)" in sql


def test_migration_downgrade_and_upgrade(app):
    config = Config(str(ROOT / "alembic.ini"))
    with app.state.engine.begin() as connection:
        config.attributes["connection"] = connection
        # A fresh migration round trip, without touching the user's database.
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert len(inspect(connection).get_table_names()) == 16


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE application_revisions SET input_hash = :hash WHERE id = :id",
        "DELETE FROM application_revisions WHERE id = :id",
    ],
)
def test_submitted_revision_rejects_direct_sql_mutation(app, operation):
    with app.state.session_factory() as db:
        user, _, applications = business_rows(db)
        rev = revision(db, applications[0], user)
        rev_id = rev.id.hex
        db.commit()
        with pytest.raises(IntegrityError, match="immutable"):
            db.execute(text(operation), {"id": rev_id, "hash": "b" * 64})
        db.rollback()
        assert db.scalar(select(ApplicationRevision)).input_hash == "a" * 64


@pytest.mark.parametrize(
    "month,inflow",
    [
        (date(2026, 9, 2), Decimal("100.00")),
        (date(2026, 9, 1), Decimal("-0.01")),
    ],
)
def test_financial_constraints(app, month, inflow):
    with app.state.session_factory() as db:
        _, company, _ = business_rows(db)
        db.add(
            CompanyFinancialMonth(
                company_id=company.id,
                month=month,
                cash_inflow=inflow,
                operating_outflow=Decimal("1.00"),
                existing_debt_payment=Decimal("0"),
                source="DEMO",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_money_defaults_and_no_implicit_confirmation(app):
    with app.state.session_factory() as db:
        _, company, applications = business_rows(db)
        assert applications[0].draft_data["confirmations"] == {
            "data_confirmed": False,
            "credit_history_check_allowed": False,
        }
        db.add(
            CompanyFinancialMonth(
                company_id=company.id,
                month=date(2026, 9, 1),
                cash_inflow=Decimal("12345.67"),
                operating_outflow=Decimal("12.34"),
                existing_debt_payment=Decimal("0"),
                source="DEMO",
            )
        )
        db.commit()
        result = db.scalar(select(CompanyFinancialMonth))
        assert result.cash_inflow == Decimal("12345.67")


def test_no_duplicate_membership(app):
    with app.state.session_factory() as db:
        user, company, _ = business_rows(db)
        db.add_all([CompanyMembership(user_id=user.id, company_id=company.id) for _ in range(2)])
        with pytest.raises(IntegrityError):
            db.flush()


def test_no_duplicate_submission_key(app):
    with app.state.session_factory() as db:
        user, _, applications = business_rows(db)
        first = revision(db, applications[0], user)
        db.add(
            ApplicationRevision(
                application_id=applications[0].id,
                revision_no=2,
                submitted_by_user_id=user.id,
                source_lock_version=2,
                submission_key=first.submission_key,
                input_hash="b" * 64,
                requested_amount=Decimal("1000000"),
                term_months=12,
                purpose_code="INVENTORY",
                company_snapshot={},
                financial_snapshot={},
                product_snapshot={},
                document_refs=[],
                schema_version=2,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_decision_cannot_mix_applications_or_assessments(app):
    with app.state.session_factory() as db:
        user, _, applications = business_rows(db)
        rev = revision(db, applications[0], user)
        other_rev = revision(db, applications[1], user)
        check = assessment(db, rev)
        db.add(
            Decision(
                application_id=applications[1].id,
                revision_id=other_rev.id,
                assessment_id=check.id,
                source="AUTO",
                outcome="REJECTED",
                reason_codes=["TEST"],
                public_explanation="Test",
                policy_version="demo-policy-0.2",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_rejected_decision_cannot_contain_offer(app):
    with app.state.session_factory() as db:
        user, _, applications = business_rows(db)
        rev = revision(db, applications[0], user)
        check = assessment(db, rev)
        db.add(
            Decision(
                application_id=applications[0].id,
                revision_id=rev.id,
                assessment_id=check.id,
                source="AUTO",
                outcome="REJECTED",
                reason_codes=["TEST"],
                public_explanation="Test",
                policy_version="demo-policy-0.2",
                approved_amount=Decimal("1000000"),
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_one_open_information_request(app):
    with app.state.session_factory() as db:
        user, _, applications = business_rows(db)
        rev = revision(db, applications[0], user)
        db.add_all(
            [
                InformationRequest(
                    application_id=applications[0].id,
                    revision_id=rev.id,
                    requested_fields=["finances"],
                    message_to_client="Test",
                    status="OPEN",
                )
                for _ in range(2)
            ]
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_check_error_has_no_normalized_facts(app):
    with app.state.session_factory() as db:
        user, _, applications = business_rows(db)
        check = assessment(db, revision(db, applications[0], user))
        now = utc_now()
        db.add(
            CheckResult(
                assessment_id=check.id,
                source="BKI",
                status="ERROR",
                normalized_data={"bad": True},
                reason_codes=[],
                error_code="TIMEOUT",
                source_version="bki-mock-0.2",
                started_at=now,
                completed_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_optimistic_version_prevents_lost_updates(app):
    with app.state.session_factory() as db:
        _, _, applications = business_rows(db)
        app_id = applications[0].id
        db.commit()
    with app.state.session_factory() as first, app.state.session_factory() as second:
        one = first.get(Application, app_id)
        two = second.get(Application, app_id)
        one.purpose_details = "first"
        first.commit()
        two.purpose_details = "second"
        with pytest.raises(StaleDataError):
            second.commit()


def test_naive_session_time_rejected(app):
    from datetime import datetime

    from credit_cabinet.models import AuthSession

    with app.state.session_factory() as db:
        user = db.scalar(select(User))
        db.add(
            AuthSession(
                user_id=user.id,
                token_hash="a" * 64,
                csrf_token="b" * 43,
                created_at=datetime(2026, 10, 20),
                last_activity_at=datetime(2026, 10, 20),
                absolute_expires_at=datetime(2026, 10, 21),
                idle_expires_at=datetime(2026, 10, 21),
            )
        )
        with pytest.raises(StatementError, match="Naive datetime"):
            db.flush()
