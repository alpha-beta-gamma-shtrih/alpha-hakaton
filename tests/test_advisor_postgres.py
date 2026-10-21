from uuid import UUID

from sqlalchemy import select

from credit_cabinet.models import AdvisorReport
from tests.conftest import login
from tests.test_advisor import Model, explain
from tests.test_drafts import patch
from tests.test_drafts_postgres import SEED_PASSWORD, create
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark


def ready_postgres(client):
    draft = create(client)
    response = patch(
        client,
        draft,
        requested_amount="1000000.00",
        term_months=12,
        purpose_code="INVENTORY",
        draft_data={
            "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True}
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_postgres_report_json_roundtrip_restart_and_access(postgres_app):
    with postgres_app() as client:
        draft = ready_postgres(client)
        client.app.state.advisor = Model()
        response = explain(client, draft, "COMPARE")
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["status"] == "SUCCESS" and report["is_current"] is True
        with client.app.state.session_factory() as db:
            stored = db.get(AdvisorReport, UUID(report["id"]))
            assert stored.scenarios[0]["monthly_payment"] == "94559.60"
            assert stored.draft_lock_version == draft["version"] and stored.revision_id is None
        cookie = client.cookies.get("credit_session")
    with postgres_app() as client:
        client.cookies.set("credit_session", cookie)
        assert client.get(f"/api/applications/{draft['id']}/advisor").json() == report
        assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
        assert client.get(f"/api/applications/{draft['id']}/advisor").status_code == 404


def test_postgres_other_connection_can_save_during_generation(postgres_app):
    with postgres_app() as client, postgres_app() as editing:
        draft = ready_postgres(client)
        editing.cookies.set("credit_session", client.cookies.get("credit_session"))

        def change():
            response = patch(editing, draft, requested_amount="900000.00")
            assert response.status_code == 200, response.text

        client.app.state.advisor = Model(during=change)
        response = explain(client, draft)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["is_current"] is False
        assert report["scenarios"][0]["requested_amount"] == "1000000.00"
        with client.app.state.session_factory() as db:
            assert len(list(db.scalars(select(AdvisorReport)))) == 1
