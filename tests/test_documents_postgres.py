from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from credit_cabinet.models import Document
from tests.conftest import csrf_headers, login
from tests.test_drafts_postgres import SEED_PASSWORD, create
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark


def test_postgres_document_roundtrip_snapshot_and_restart(postgres_app):
    with postgres_app() as client:
        draft = create(client)
        url = draft["documents"][0]["download_url"]
        original = client.get(url)
        assert original.status_code == 200
        assert sha256(original.content).hexdigest() == draft["documents"][0]["content_sha256"]
        saved = client.patch(
            f"/api/applications/{draft['id']}",
            headers=csrf_headers(client),
            json={
                "expected_version": draft["version"],
                "requested_amount": "1000000.00",
                "term_months": 12,
                "purpose_code": "INVENTORY",
                "draft_data": {
                    "confirmations": {"data_confirmed": True, "credit_history_check_allowed": True}
                },
            },
        ).json()
        submitted = client.post(
            f"/api/applications/{draft['id']}/submit",
            headers=csrf_headers(client),
            json={"expected_version": saved["version"], "submission_key": str(uuid4())},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["revision"]["document_refs"] == draft["documents"]
        assert login(client, "bank@example.com", SEED_PASSWORD).status_code == 200
        assert client.get(url).content == original.content
        cookie = client.cookies.get("credit_session")
    with postgres_app() as client:
        client.cookies.set("credit_session", cookie)
        assert client.get(url).content == original.content
        assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE documents SET content_sha256 = :hash WHERE id = :id",
        "DELETE FROM documents WHERE id = :id",
    ],
)
def test_postgres_document_metadata_trigger(postgres_app, operation):
    with postgres_app() as client:
        draft = create(client)
        document_id = UUID(draft["documents"][0]["id"])
        with client.app.state.session_factory() as db:
            with pytest.raises(IntegrityError, match="immutable"):
                db.execute(text(operation), {"id": document_id, "hash": "b" * 64})
            db.rollback()
            assert (
                db.get(Document, document_id).content_sha256
                == draft["documents"][0]["content_sha256"]
            )
