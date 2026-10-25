"""Persistent, server-owned options. Selecting an option never rebases the set."""

import logging
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm.exc import StaleDataError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.security import utc_now
from credit_cabinet.models import CreditProduct
from credit_cabinet.schemas.scenarios import (
    ScenarioSetResponse,
    ScenarioSetUpdate,
    ScenariosResponse,
)
from credit_cabinet.services.access import client_application
from credit_cabinet.services.advisor_context import fixture_stamp
from credit_cabinet.services.drafts import draft_view, remember_draft
from credit_cabinet.services.exposure import service_exposure
from credit_cabinet.services.scenarios import prepare_comparison
from credit_cabinet.services.snapshots import application_input, financial_input_hash
from credit_cabinet.services.submissions import latest_assessment, latest_revision

logger = logging.getLogger(__name__)
EDITABLE = {"DRAFT", "NEEDS_INFO"}


def context_hash(db, application, settings):
    payload = application_input(db, application, require_confirmation=False)
    # Amount/term are checked against the selected option separately. Descriptive
    # text, step changes and confirmation of data do not affect the calculation.
    payload.pop("requested_amount")
    payload.pop("term_months")
    financials = payload["financial_snapshot"]
    for key in ("purpose_details", "info_response"):
        financials.pop(key, None)
    financials["confirmations"].pop("data_confirmed", None)
    revision = latest_revision(db, application.id)
    assessment = latest_assessment(db, revision.id) if revision else None
    return financial_input_hash(
        {
            "input": payload,
            "service_exposure": service_exposure(
                db, application.company_id, exclude_application_id=application.id
            ),
            "sources": fixture_stamp(settings.demo_dataset_dir),
            "revision_id": str(revision.id) if revision else None,
            "assessment_id": str(assessment.id) if assessment else None,
        }
    )


def current(db, application, settings):
    stored = application.scenario_set
    if application.status not in EDITABLE:
        return False, "Заявка уже отправлена; изменение условий недоступно."
    if stored.get("manually_changed"):
        return False, "Сумма или срок изменены вручную. Обновите варианты."
    try:
        if stored["context_hash"] != context_hash(db, application, settings):
            return False, "Расчётные данные или условия изменились. Обновите варианты."
    except APIError:
        return False, "Проверьте параметры заявки и обновите варианты."
    selected = next(
        (
            row
            for row in stored["candidates"]
            if row["candidate_id"] == stored["selected_candidate_id"]
        ),
        None,
    )
    if selected is None or (
        application.requested_amount != Decimal(selected["requested_amount"])
        or application.term_months != selected["term_months"]
    ):
        return False, "Параметры заявки не совпадают с выбранным вариантом. Обновите варианты."
    return True, None


def view(db, application, settings):
    stored = application.scenario_set
    if stored is None:
        return None
    is_current, reason = current(db, application, settings)
    consent = (
        application.draft_data.get("confirmations", {}).get("credit_history_check_allowed") is True
    )
    # Revocation must also hide previously computed credit-derived data.
    visible = consent or stored["mode"] == "CALCULATION_ONLY"
    return ScenarioSetResponse(
        id=stored["id"],
        created_at=stored["created_at"],
        application_version=application.lock_version,
        mode=stored["mode"] if visible else "CALCULATION_ONLY",
        candidates=deepcopy(stored["candidates"]) if visible else [],
        selected_candidate_id=stored["selected_candidate_id"] if is_current else None,
        is_current=is_current,
        stale_reason=reason,
    )


def read(db, user_id, application_id, settings):
    application = client_application(db, user_id, application_id)
    return view(db, application, settings)


def editable(db, principal, application_id, expected_version):
    application = client_application(db, principal.user.id, application_id, lock=True)
    if application.status not in EDITABLE:
        raise APIError(409, "APPLICATION_NOT_EDITABLE", "Условия отправленной заявки менять нельзя")
    if application.lock_version != expected_version:
        raise APIError(409, "VERSION_CONFLICT", "Заявка уже изменена; получите актуальную версию")
    return application


def response(db, application, settings):
    return ScenarioSetUpdate(
        application=draft_view(application, db.get(CreditProduct, application.product_id), db),
        scenario_set=view(db, application, settings),
    )


def save(db, application, principal, auth, event):
    application.lock_version += 1
    application.updated_at = utc_now()
    remember_draft(principal, application)
    auth.activity(db, principal, commit=False)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(
            409, "VERSION_CONFLICT", "Заявка уже изменена; получите актуальную версию"
        ) from None
    logger.info(
        event,
        extra={
            "application_id": str(application.id),
            "user_id": str(principal.user.id),
            "version": application.lock_version,
        },
    )


def create(db, principal, application_id, body, auth, sources):
    application = editable(db, principal, application_id, body.expected_version)
    if application.scenario_set is not None and not body.refresh:
        return response(db, application, auth.settings)
    comparison = prepare_comparison(db, principal.user.id, application_id, body, sources)
    application.scenario_set = {
        "id": str(uuid4()),
        "created_at": utc_now().isoformat(),
        "mode": comparison.response.mode,
        "candidates": comparison.response.model_dump(mode="json")["candidates"],
        "context_hash": context_hash(db, application, auth.settings),
        "selected_candidate_id": "REQUESTED",
        "manually_changed": False,
    }
    save(db, application, principal, auth, "application.scenario_set_created")
    return response(db, application, auth.settings)


def select(db, principal, application_id, body, auth):
    application = editable(db, principal, application_id, body.expected_version)
    stored = application.scenario_set
    if stored is None or stored["id"] != str(body.scenario_set_id):
        raise APIError(409, "SCENARIO_SET_CONFLICT", "Набор вариантов изменён; обновите страницу")
    is_current, reason = current(db, application, auth.settings)
    if not is_current:
        raise APIError(409, "SCENARIO_SET_STALE", reason)
    option = next(
        (row for row in stored["candidates"] if row["candidate_id"] == body.candidate_id), None
    )
    if option is None:
        raise APIError(422, "SCENARIO_NOT_FOUND", "В этом наборе нет выбранного варианта")
    if stored["selected_candidate_id"] != body.candidate_id:
        application.requested_amount = Decimal(option["requested_amount"])
        application.term_months = option["term_months"]
        application.scenario_set = {**stored, "selected_candidate_id": body.candidate_id}
        save(db, application, principal, auth, "application.scenario_selected")
    return response(db, application, auth.settings)


def use_saved_comparison(db, application, comparison, settings):
    """Keep the existing AI comparison aligned with displayed options; no new AI feature."""
    stored = view(db, application, settings)
    if stored is None or application.status not in EDITABLE:
        return comparison
    if not stored.is_current:
        raise APIError(409, "SCENARIO_SET_STALE", stored.stale_reason)
    comparison.response = ScenariosResponse(
        mode=stored.mode,
        application_version=application.lock_version,
        candidates=stored.candidates,
    )
    return comparison
