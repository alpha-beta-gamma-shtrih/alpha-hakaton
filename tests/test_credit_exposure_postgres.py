from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

from sqlalchemy import select

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import Application, Decision
from credit_cabinet.schemas.agreements import SignAgreementRequest
from credit_cabinet.schemas.bank import ManualDecision
from credit_cabinet.schemas.submissions import SubmitRequest
from credit_cabinet.services.agreements import sign
from credit_cabinet.services.bank_commands import decide
from credit_cabinet.services.exposure import service_exposure
from credit_cabinet.services.submissions import submit
from tests.conftest import SEED_PASSWORD, login
from tests.test_advisor_postgres import ready_postgres
from tests.test_agreements import sign_body, url
from tests.test_bank_commands import decision_body
from tests.test_bank_postgres import submitted_for_review
from tests.test_drafts import patch
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark
from tests.test_submissions import send


def parallel(client, apps, operation):
    cookie = client.cookies.get("credit_session")
    auth, factory = client.app.state.auth, client.app.state.session_factory
    barrier = Barrier(len(apps))

    def writer(index):
        with factory() as db:
            principal = auth.authenticate(db, cookie)
            barrier.wait(timeout=15)
            try:
                operation(db, principal, apps[index], auth)
                return 200
            except APIError as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=len(apps)) as pool:
        return sorted(pool.map(writer, range(len(apps))))


def test_parallel_submissions_of_different_applications_share_company_limit(postgres_app):
    with postgres_app() as client:
        apps = [
            patch(client, ready_postgres(client), requested_amount="1800000.00").json()
            for _ in range(2)
        ]

        def operation(db, principal, app, auth):
            submit(
                db,
                principal,
                UUID(app["id"]),
                SubmitRequest(expected_version=app["version"], submission_key=uuid4()),
                auth,
                client.app.state.sources,
            )

        assert parallel(client, apps, operation) == [200, 200]
        states = [client.get(f"/api/applications/{app['id']}").json()["status"] for app in apps]
        assert sorted(states) == ["APPROVED", "REJECTED"]
        with client.app.state.session_factory() as db:
            assert service_exposure(db, UUID(apps[0]["company_id"]))["reserved_count"] == 1


def test_parallel_bank_approvals_do_not_both_reserve_same_capacity(postgres_app):
    with postgres_app() as client:
        apps = [submitted_for_review(client)["application"] for _ in range(2)]
        assert login(client, "bank@example.com", SEED_PASSWORD).status_code == 200

        def operation(db, principal, app, auth):
            decide(
                db,
                principal,
                UUID(app["id"]),
                ManualDecision.model_validate(decision_body(app["version"])),
                auth,
            )

        assert parallel(client, apps, operation) == [200, 422]


def test_parallel_signatures_of_legacy_overcommitted_approvals_are_rechecked(postgres_app):
    with postgres_app() as client:
        apps = []
        for _ in range(2):
            draft = patch(client, ready_postgres(client), requested_amount="1800000.00").json()
            apps.append(send(client, draft).json()["application"])
        # Reproduce approvals issued by the old version which ignored other applications.
        with client.app.state.session_factory() as db:
            for app in apps:
                row = db.get(Application, UUID(app["id"]))
                row.status = "APPROVED"
                decision = db.scalar(select(Decision).where(Decision.application_id == row.id))
                decision.outcome = "APPROVED"
                decision.approved_amount = Decimal("1800000")
                decision.approved_term_months = 12
                decision.annual_rate_percent = Decimal("24")
                decision.monthly_payment = Decimal(
                    app["assessment"]["calculation_details"]["monthly_payment"]
                )
            db.commit()
        apps = [client.get(f"/api/applications/{app['id']}").json() for app in apps]
        bodies = {
            app["id"]: SignAgreementRequest.model_validate(
                sign_body(app, client.get(url(app)).json())
            )
            for app in apps
        }

        def operation(db, principal, app, auth):
            sign(db, principal, UUID(app["id"]), bodies[app["id"]], auth)

        assert parallel(client, apps, operation) == [200, 409]
        states = [client.get(f"/api/applications/{app['id']}").json()["status"] for app in apps]
        assert sorted(states) == ["MANUAL_REVIEW", "SIGNED"]
        cookie = client.cookies.get("credit_session")
    with postgres_app() as client:
        client.cookies.set("credit_session", cookie)
        with client.app.state.session_factory() as db:
            exposure = service_exposure(db, UUID(apps[0]["company_id"]))
            assert exposure["signed_count"] == 1 and exposure["reserved_count"] == 0
