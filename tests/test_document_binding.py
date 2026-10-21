from copy import deepcopy
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from credit_cabinet.integrations.documents import DocumentStore
from credit_cabinet.models import Application, ApplicationEvent, ApplicationRevision, Document
from tests.conftest import ROOT
from tests.test_drafts import new_draft
from tests.test_submissions import ready, send


def test_draft_copies_profile_document_and_submit_freezes_reference(seeded, client):
    draft = ready(client)
    assert len(draft["documents"]) == 1
    document = draft["documents"][0]
    content = (ROOT / "demo_data/demo_0_2/documents/C01.csv").read_bytes()
    assert document["application_id"] == draft["id"]
    assert document["source"] == "DEMO"
    assert document["content_sha256"] == sha256(content).hexdigest()
    assert document["size_bytes"] == len(content)
    assert "storage_key" not in document
    with seeded.state.session_factory() as db:
        stored = db.get(Document, UUID(document["id"]))
        assert DocumentStore(seeded.state.settings).read(stored) == content
    response = send(client, draft).json()
    assert response["revision"]["document_refs"] == draft["documents"]
    key = response["revision"]["submission_key"]
    assert send(client, draft, key=UUID(key)).json()["revision"] == response["revision"]
    with seeded.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 1


@pytest.mark.parametrize(
    "operation", ["UPDATE documents SET size_bytes = 1", "DELETE FROM documents"]
)
def test_document_metadata_is_immutable_in_database(seeded, client, operation):
    new_draft(client)
    with seeded.state.session_factory() as db:
        with pytest.raises(IntegrityError, match="immutable"):
            db.execute(text(operation))
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Document)) == 1


@pytest.mark.parametrize("confirmed", [False, True])
def test_legacy_draft_attached_only_on_new_valid_submission(seeded, client, confirmed):
    original = ready(client)
    with seeded.state.session_factory() as db:
        source = db.get(Application, UUID(original["id"]))
        legacy = Application(
            company_id=source.company_id,
            created_by_user_id=source.created_by_user_id,
            product_id=source.product_id,
            status="DRAFT",
            ui_step=source.ui_step,
            calculation_date=source.calculation_date,
            requested_amount=source.requested_amount,
            term_months=source.term_months,
            purpose_code=source.purpose_code,
            draft_data=deepcopy(source.draft_data),
        )
        db.add(legacy)
        data = deepcopy(legacy.draft_data)
        data["confirmations"]["data_confirmed"] = confirmed
        legacy.draft_data = data
        db.commit()
        legacy_id = str(legacy.id)
    draft = client.get(f"/api/applications/{legacy_id}").json()
    assert draft["documents"] == []
    response = send(client, draft)
    if not confirmed:
        assert response.status_code == 422
        with seeded.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(Document)) == 1
            assert db.scalar(select(func.count()).select_from(ApplicationRevision)) == 0
        return
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["revision"]["document_refs"][0]["application_id"] == legacy_id
    with seeded.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 2
        assert db.scalar(select(func.count()).select_from(ApplicationRevision)) == 1


def test_corrupt_storage_blocks_submit_without_partial_revision(seeded, client):
    draft = ready(client)
    with seeded.state.session_factory() as db:
        row = db.get(Document, UUID(draft["documents"][0]["id"]))
        DocumentStore(seeded.state.settings).path(row.storage_key).write_bytes(b"changed")
    result = send(client, draft)
    assert result.status_code == 503
    assert result.json()["code"] == "DOCUMENT_UNAVAILABLE"
    assert client.get(f"/api/applications/{draft['id']}").json()["version"] == draft["version"]
    with seeded.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ApplicationRevision)) == 0


def test_template_failure_rolls_back_application_and_event(seeded, client, tmp_path):
    from tests.conftest import csrf_headers, login

    assert login(client).status_code == 200
    company = client.get("/api/companies").json()["items"][0]["id"]
    product = client.get("/api/products").json()["items"][0]["id"]
    seeded.state.settings.demo_dataset_dir = tmp_path / "missing"
    response = client.post(
        "/api/applications",
        json={"company_id": company, "product_id": product},
        headers=csrf_headers(client),
    )
    assert response.status_code == 503
    with seeded.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Application)) == 0
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(ApplicationEvent)) == 0
