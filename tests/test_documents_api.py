from copy import deepcopy
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from credit_cabinet.integrations.documents import DocumentStore
from credit_cabinet.models import (
    ApplicationRevision,
    CompanyMembership,
    Document,
    User,
)
from tests.conftest import ROOT, SEED_PASSWORD, csrf_headers, login
from tests.test_drafts import new_draft
from tests.test_submissions import ready, send


def url(draft):
    return draft["documents"][0]["download_url"]


def test_client_download_with_cookie_without_csrf(seeded, client):
    draft = new_draft(client)
    response = client.get(url(draft))
    content = (ROOT / "demo_data/demo_0_2/documents/C01.csv").read_bytes()
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"].startswith("attachment; filename=")
    assert response.headers["x-content-sha256"] == sha256(content).hexdigest()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    with seeded.state.session_factory() as db:
        # Storage keys aren't web routes, even for an authenticated client.
        document = db.get(Document, UUID(draft["documents"][0]["id"]))
        assert client.get("/" + document.storage_key).status_code == 404
        assert client.get("/.data/documents/" + document.storage_key).status_code == 404


@pytest.mark.parametrize("submitted", [False, True])
def test_other_client_and_anonymous_cannot_download(seeded, client, submitted):
    draft = ready(client)
    if submitted:
        assert send(client, draft).status_code == 200
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    existing = client.get(url(draft))
    missing = client.get(f"/api/documents/{uuid4()}")
    assert existing.status_code == missing.status_code == 404
    assert existing.json()["code"] == missing.json()["code"] == "DOCUMENT_NOT_FOUND"
    client.cookies.clear()
    assert client.get(url(draft)).status_code == 401


def test_access_rechecked_after_membership_revocation(seeded, client):
    draft = new_draft(client)
    assert client.get(url(draft)).status_code == 200
    with seeded.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "client@example.com"))
        db.execute(delete(CompanyMembership).where(CompanyMembership.user_id == user.id))
        db.commit()
    assert client.get(url(draft)).status_code == 404


def test_bank_only_downloads_sent_attachments(seeded, client):
    draft = ready(client)
    with TestClient(seeded) as bank:
        assert login(bank, "bank@example.com").status_code == 200
        assert bank.get(url(draft)).status_code == 404
        result = send(client, draft).json()
        bank_card = bank.get(f"/api/bank/applications/{draft['id']}").json()
        assert bank_card["revision"]["document_refs"] == result["revision"]["document_refs"]
        response = bank.get(url(draft))
        assert response.status_code == 200
        assert response.headers["x-content-sha256"] == draft["documents"][0]["content_sha256"]
        # Simulate a future new attachment while the application already has a revision.
        # Bank access must not depend just on application.status or on company membership.
        with seeded.state.session_factory() as db:
            original = db.get(Document, UUID(draft["documents"][0]["id"]))
            store = DocumentStore(seeded.state.settings)
            document_id = uuid4()
            extra = Document(
                id=document_id,
                application_id=original.application_id,
                created_by_user_id=original.created_by_user_id,
                kind=original.kind,
                original_filename=original.original_filename,
                mime_type=original.mime_type,
                storage_key=store.save(
                    original.application_id,
                    document_id,
                    original.content_sha256,
                    store.read(original),
                ),
                content_sha256=original.content_sha256,
                size_bytes=original.size_bytes,
                source=original.source,
            )
            db.add(extra)
            db.commit()
        assert client.get(f"/api/documents/{document_id}").status_code == 200
        assert bank.get(f"/api/documents/{document_id}").status_code == 404
        assert bank.get(url(draft)).status_code == 200


@pytest.mark.parametrize("failure", ["missing", "corrupt", "large"])
def test_invalid_content_is_never_returned(seeded, client, failure):
    draft = ready(client)
    with seeded.state.session_factory() as db:
        document = db.get(Document, UUID(draft["documents"][0]["id"]))
        path = DocumentStore(seeded.state.settings).path(document.storage_key)
        if failure == "missing":
            path.unlink()
        else:
            path.write_bytes(b"secret" if failure == "corrupt" else b"x" * (2 * 1024 * 1024 + 1))
    response = client.get(url(draft))
    assert response.status_code == 503
    assert response.json()["code"] == "DOCUMENT_UNAVAILABLE"
    assert "secret" not in response.text and "storage_key" not in response.text
    assert "content-disposition" not in response.headers
    assert client.get(f"/api/applications/{draft['id']}").json()["status"] == "DRAFT"
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    assert client.get(url(draft)).status_code == 404  # Authorization precedes filesystem access.


def test_download_and_restart_do_not_touch_session_idle_time(seeded, client):
    draft = new_draft(client)
    before = client.get("/api/auth/me").json()
    cookie = client.cookies.get("credit_session")
    with TestClient(seeded) as restarted:
        restarted.cookies.set("credit_session", cookie)
        assert restarted.get(url(draft)).status_code == 200
    assert client.get("/api/auth/me").json() == before


def test_old_snapshot_replay_never_gains_new_document_references(seeded, client):
    draft = ready(client)
    result = send(client, draft).json()
    revision_data = result["revision"]
    # Represent an existing pre-feature revision without changing its immutable row.
    with seeded.state.session_factory() as db:
        source = db.get(ApplicationRevision, UUID(revision_data["id"]))
        legacy = ApplicationRevision(
            application_id=source.application_id,
            revision_no=2,
            submitted_by_user_id=source.submitted_by_user_id,
            source_lock_version=source.source_lock_version,
            submission_key=uuid4(),
            input_hash=source.input_hash,
            requested_amount=source.requested_amount,
            term_months=source.term_months,
            purpose_code=source.purpose_code,
            company_snapshot=deepcopy(source.company_snapshot),
            financial_snapshot=deepcopy(source.financial_snapshot),
            product_snapshot=deepcopy(source.product_snapshot),
            document_refs=[],
            schema_version=2,
        )
        db.add(legacy)
        db.commit()
        key = legacy.submission_key
    replay = send(client, draft, key=key)
    assert replay.status_code == 200
    assert replay.json()["revision"]["document_refs"] == []
    assert client.get(f"/api/applications/{draft['id']}/revisions/2").json()["document_refs"] == []


def test_unsafe_download_methods_are_not_exposed(seeded, client):
    draft = new_draft(client)
    assert client.post(url(draft), headers=csrf_headers(client)).status_code == 405
    assert client.delete(url(draft), headers=csrf_headers(client)).status_code == 405
    assert client.get("/api/documents/not-a-uuid").status_code == 422


def test_expired_session_cannot_download(seeded, client, monkeypatch):
    from datetime import timedelta

    from credit_cabinet.core.security import utc_now

    draft = new_draft(client)
    future = utc_now() + timedelta(hours=2)
    monkeypatch.setattr("credit_cabinet.services.auth.utc_now", lambda: future)
    assert client.get(url(draft)).status_code == 401
