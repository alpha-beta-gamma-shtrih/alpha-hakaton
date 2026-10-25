from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from credit_cabinet.api.errors import APIError
from credit_cabinet.integrations.fixtures import FixtureSources
from credit_cabinet.schemas.scenarios import ScenarioSelectRequest
from credit_cabinet.services.scenario_sets import select as select_option
from credit_cabinet.services.seed import import_bundle
from tests.conftest import ROOT, SEED_PASSWORD, login, personal_bootstrap_bundle
from tests.test_drafts import patch
from tests.test_drafts_postgres import create
from tests.test_drafts_postgres import postgres_app as postgres_app
from tests.test_drafts_postgres import pytestmark as pytestmark
from tests.test_scenario_sets import check_switching, create_set, endpoint


def configure(client):
    directory = ROOT / "demo_data/demo_0_3"
    client.app.state.settings.demo_dataset_dir = directory
    client.app.state.sources = FixtureSources(directory)


def prepare(client):
    configure(client)
    with client.app.state.session_factory() as db:
        import_bundle(db, personal_bootstrap_bundle())
    draft = create(client)
    draft = patch(
        client,
        draft,
        requested_amount="2600000.00",
        term_months=20,
        purpose_code="INVENTORY",
        draft_data={
            "confirmations": {
                "data_confirmed": True,
                "credit_history_check_allowed": True,
            }
        },
    ).json()
    result = create_set(client, draft)
    assert result.status_code == 200, result.text
    return result.json()["application"], result.json()["scenario_set"]


def test_postgres_json_roundtrip_switching_and_restart(postgres_app):
    with postgres_app() as client:
        draft, options = prepare(client)
        draft = check_switching(client, draft, options)
    with postgres_app() as restarted:
        configure(restarted)
        assert login(restarted, password=SEED_PASSWORD).status_code == 200
        stored = restarted.get(endpoint(draft)).json()
        assert stored["id"] == options["id"] and stored["is_current"]
        assert stored["candidates"] == options["candidates"]


def test_postgres_two_selections_cannot_overwrite_each_other(postgres_app):
    with postgres_app() as client:
        draft, options = prepare(client)
        app = client.app
        cookie = client.cookies.get("credit_session")
        barrier = Barrier(2)

        def choose(candidate):
            with app.state.session_factory() as db:
                principal = app.state.auth.authenticate(db, cookie)
                body = ScenarioSelectRequest(
                    expected_version=draft["version"],
                    scenario_set_id=options["id"],
                    candidate_id=candidate,
                )
                barrier.wait(timeout=10)
                try:
                    select_option(db, principal, UUID(draft["id"]), body, app.state.auth)
                    return 200
                except APIError as error:
                    return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(choose, ["LOWER_AMOUNT", "LONGER_TERM"]))
        assert sorted(outcomes) == [200, 409]
        result = client.get(endpoint(draft)).json()
        assert result["id"] == options["id"] and result["is_current"]
        assert result["candidates"] == options["candidates"]
