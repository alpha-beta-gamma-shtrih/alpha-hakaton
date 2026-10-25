from tests.conftest import SEED_PASSWORD, login
from tests.test_advisor_postgres import ready_postgres
from tests.test_agreements import sign, sign_body, url
from tests.test_company_files import endpoint
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark
from tests.test_submissions import send


def test_company_files_survive_restart_with_original_signed_terms(postgres_app):
    with postgres_app() as client:
        app = send(client, ready_postgres(client)).json()["application"]
        document = client.get(url(app)).json()
        assert sign(client, app, sign_body(app, document)).status_code == 200
        agreements = client.get(endpoint("agreements")).json()
        documents = client.get(endpoint("documents")).json()
        assert agreements["total"] == documents["total"] == 1
        assert agreements["items"][0]["content"] == document["content"]
        assert documents["items"][0]["application_status"] == "SIGNED"
    with postgres_app() as client:
        assert login(client, password=SEED_PASSWORD).status_code == 200
        assert client.get(endpoint("agreements")).json() == agreements
        assert client.get(endpoint("documents")).json() == documents
        assert client.get(documents["items"][0]["download_url"]).status_code == 200
