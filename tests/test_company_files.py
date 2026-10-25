from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from credit_cabinet.models import CompanyMembership, User
from tests.conftest import SEED_PASSWORD, csrf_headers, login
from tests.test_agreements import approved, sign, sign_body, url
from tests.test_drafts import C01, C02, new_draft


def endpoint(kind, company_id=C01):
    return f"/api/companies/{company_id}/{kind}"


def signed(client):
    app = approved(client)
    agreement = client.get(url(app)).json()
    response = sign(client, app, sign_body(app, agreement))
    assert response.status_code == 200, response.text
    return response.json(), client.get(url(app)).json()


def test_only_signed_agreements_appear_and_exact_content_is_preserved(seeded, client):
    app = approved(client)
    assert client.get(endpoint("agreements")).json()["items"] == []
    document = client.get(url(app)).json()
    assert sign(client, app, sign_body(app, document)).status_code == 200
    saved = client.get(url(app)).json()
    # Add an unsigned approval: it belongs in applications, not signed contracts.
    approved(client)
    response = client.get(endpoint("agreements"))
    assert response.status_code == 200
    assert response.json() == {"items": [saved], "total": 1, "limit": 20, "offset": 0}
    assert saved["content"] == document["content"]
    assert "risk_score" not in response.text and "signed_by_user_id" not in response.text


def test_documents_include_drafts_and_downloads_but_exclude_archived_drafts(seeded, client):
    first, second = new_draft(client), new_draft(client)
    response = client.get(endpoint("documents"))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {row["application_id"] for row in data["items"]} == {first["id"], second["id"]}
    assert all(row["application_status"] == "DRAFT" for row in data["items"])
    assert all(
        "storage_key" not in row and "created_by_user_id" not in row for row in data["items"]
    )
    for row in data["items"]:
        download = client.get(row["download_url"])
        assert download.status_code == 200
        assert download.headers["x-content-sha256"] == row["content_sha256"]
    assert (
        client.request(
            "DELETE",
            f"/api/applications/{first['id']}",
            json={"expected_version": first["version"]},
            headers=csrf_headers(client),
        ).status_code
        == 204
    )
    remaining = client.get(endpoint("documents")).json()
    assert remaining["total"] == 1 and remaining["items"][0]["application_id"] == second["id"]
    assert client.get(first["documents"][0]["download_url"]).status_code == 404


@pytest.mark.parametrize("kind", ["agreements", "documents"])
def test_company_files_check_role_membership_and_unknown_ids(seeded, client, kind):
    signed(client)
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    assert client.get(endpoint(kind)).status_code == 404
    assert client.get(endpoint(kind, str(uuid4()))).status_code == 404
    assert client.get(endpoint(kind, C02)).json()["total"] == 0
    assert login(client, "bank@example.com").status_code == 200
    assert client.get(endpoint(kind)).status_code == 403
    client.cookies.clear()
    assert client.get(endpoint(kind)).status_code == 401


def test_company_members_can_read_each_others_files_and_access_is_revocable(seeded, client):
    app, _ = signed(client)
    with seeded.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "client2@example.com"))
        user_id = user.id
        db.add(CompanyMembership(user_id=user_id, company_id=UUID(C01)))
        db.commit()
    assert login(client, "client2@example.com", SEED_PASSWORD).status_code == 200
    assert client.get(endpoint("agreements")).json()["total"] == 1
    assert client.get(endpoint("documents")).json()["total"] == 1
    with seeded.state.session_factory() as db:
        db.execute(
            delete(CompanyMembership).where(
                CompanyMembership.user_id == user_id, CompanyMembership.company_id == UUID(C01)
            )
        )
        db.commit()
    assert client.get(endpoint("agreements")).status_code == 404
    assert client.get(endpoint("documents")).status_code == 404
    assert client.get(url(app)).status_code == 404
    assert client.get(app["documents"][0]["download_url"]).status_code == 404


@pytest.mark.parametrize("kind", ["agreements", "documents"])
def test_pagination_is_stable_and_empty_pages_keep_total(seeded, client, kind):
    signed(client)
    signed(client)
    first = client.get(endpoint(kind) + "?limit=1").json()
    second = client.get(endpoint(kind) + "?limit=1&offset=1").json()
    assert first["total"] == second["total"] == 2
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"] != second["items"]
    assert client.get(endpoint(kind) + "?limit=1").json() == first
    assert client.get(endpoint(kind) + "?limit=1&offset=2").json() == {
        "items": [],
        "total": 2,
        "limit": 1,
        "offset": 2,
    }
    assert client.get(endpoint(kind) + "?limit=101").status_code == 422
    assert client.get(endpoint(kind) + "?offset=-1").status_code == 422
