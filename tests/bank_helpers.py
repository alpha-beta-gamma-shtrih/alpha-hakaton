from copy import deepcopy

from tests.test_drafts import patch
from tests.test_submissions import ready, send


def review_application(client, mode="borderline"):
    draft = ready(client)
    months = deepcopy(draft["draft_data"]["financial_months"])
    for index, row in enumerate(months):
        if mode == "zero_baseline":
            row.update(cash_inflow="0.00" if index < 3 else "2000000.00", operating_outflow="0.00")
        else:
            row["cash_inflow"] = "1020000.00"
    draft = patch(client, draft, draft_data={"financial_months": months}).json()
    response = send(client, draft)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application"]["status"] == "MANUAL_REVIEW", body
    return body
