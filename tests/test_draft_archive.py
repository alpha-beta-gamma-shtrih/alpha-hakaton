from uuid import UUID

import pytest
from sqlalchemy import func, select

from credit_cabinet.models import AdvisorReport, Application, ApplicationEvent, Document
from tests.conftest import SEED_PASSWORD, csrf_headers, login
from tests.test_advisor import Model, explain
from tests.test_drafts import C01, new_draft, patch
from tests.test_submissions import ready, send


def archive(client, draft, **fields):
    return client.request(
        "DELETE",
        f"/api/applications/{draft['id']}",
        json={"expected_version": draft["version"], **fields},
        headers=csrf_headers(client),
    )


def test_archive_hides_draft_and_related_resources_without_deleting_history(seeded, client):
    draft = ready(client)
    report = explain(client, draft).json()
    document = draft["documents"][0]
    response = archive(client, draft)
    assert response.status_code == 204 and response.content == b""
    for url in (
        f"/api/applications/{draft['id']}",
        f"/api/applications/{draft['id']}/events",
        f"/api/applications/{draft['id']}/advisor",
        f"/api/applications/{draft['id']}/advisor-reports/{report['id']}",
        document["download_url"],
    ):
        assert client.get(url).status_code == 404, url
    assert client.get("/api/applications").json()["total"] == 0
    assert client.get(f"/api/applications?company_id={C01}").json()["total"] == 0
    assert archive(client, draft).status_code == 404
    assert patch(client, draft, requested_amount="200000.00").status_code == 404
    assert send(client, draft).status_code == 404
    assert explain(client, draft).status_code == 404
    assert client.get("/api/auth/me").json()["user"]["ui_context"] == {"section": "applications"}
    with seeded.state.session_factory() as db:
        saved = db.get(Application, UUID(draft["id"]))
        assert saved.archived_at is not None and saved.lock_version == draft["version"] + 1
        assert saved.status == "DRAFT"
        assert db.get(Document, UUID(document["id"])) is not None
        assert db.get(AdvisorReport, UUID(report["id"])) is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationEvent)
                .where(
                    ApplicationEvent.application_id == saved.id,
                    ApplicationEvent.event_type == "DRAFT_ARCHIVED",
                )
            )
            == 1
        )


def test_archive_requires_current_version_and_keeps_other_drafts(seeded, client):
    draft = new_draft(client)
    current = patch(client, draft, purpose_code="INVENTORY").json()
    assert archive(client, draft).status_code == 409
    other = new_draft(client)
    assert archive(client, current).status_code == 204
    page = client.get("/api/applications?limit=1").json()
    assert page["total"] == 1 and page["items"][0]["id"] == other["id"]


@pytest.mark.parametrize("email,status", [("client2@example.com", 404), ("bank@example.com", 403)])
def test_archive_enforces_company_and_role(seeded, client, email, status):
    draft = new_draft(client)
    login(client, email, SEED_PASSWORD if email.startswith("client2") else "Test-password-only-29!")
    assert archive(client, draft).status_code == status
    with seeded.state.session_factory() as db:
        assert db.get(Application, UUID(draft["id"])).archived_at is None


def test_archive_requires_csrf_origin_and_strict_body(seeded, client):
    draft = new_draft(client)
    url = f"/api/applications/{draft['id']}"
    assert client.request("DELETE", url, json={"expected_version": 1}).status_code == 403
    assert archive(client, draft, unexpected=True).status_code == 422
    assert archive(client, draft, expected_version=True).status_code == 422


@pytest.mark.parametrize("needs_info", [False, True])
def test_submitted_applications_cannot_be_archived(seeded, client, needs_info):
    draft = ready(client)
    if needs_info:
        draft = patch(client, draft, draft_data={"financial_months": []}).json()
    submitted = send(client, draft).json()["application"]
    assert submitted["status"] == ("NEEDS_INFO" if needs_info else "APPROVED")
    response = archive(client, submitted)
    assert response.status_code == 409
    assert response.json()["code"] == "APPLICATION_NOT_DELETABLE"
    assert client.get(f"/api/applications/{draft['id']}").status_code == 200


def test_archive_during_generation_prevents_saving_report(seeded, client):
    draft = ready(client)
    seeded.state.advisor = Model(during=lambda: archive(client, draft))
    assert explain(client, draft).status_code == 404
    with seeded.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AdvisorReport)) == 0
