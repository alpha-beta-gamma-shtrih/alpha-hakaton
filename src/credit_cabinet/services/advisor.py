"""Short read/generate/write phases; a model never holds an application transaction."""

import logging
from copy import deepcopy
from time import perf_counter

from sqlalchemy import select

from credit_cabinet.api.errors import APIError
from credit_cabinet.integrations.ollama import GENERATION_CONFIG, PROMPT_VERSION
from credit_cabinet.models import AdvisorReport
from credit_cabinet.models.enums import ReportStatus
from credit_cabinet.schemas.advisor import AdvisorResponse
from credit_cabinet.services.access import bank_application, client_application
from credit_cabinet.services.advisor_context import (
    basis_hash,
    build_facts,
    fallback_selection,
    fixture_stamp,
    render,
    require_confirmation,
    valid_selection,
)
from credit_cabinet.services.policy import canonical_hash
from credit_cabinet.services.scenario_sets import use_saved_comparison
from credit_cabinet.services.scenarios import prepare_comparison

logger = logging.getLogger(__name__)


def current(db, application, report, settings):
    try:
        if report.context_snapshot["basis_hash"] != basis_hash(db, application):
            return False
        if report.context_snapshot["assessment_id"] is None:
            return report.context_snapshot["fixture_stamp"] == fixture_stamp(
                settings.demo_dataset_dir
            )
        return True
    except APIError:
        # E.g. the product was deactivated or the current draft became incomplete.
        return False


def view(db, application, report, settings):
    return AdvisorResponse(
        id=report.id,
        application_id=report.application_id,
        revision_id=report.revision_id,
        draft_lock_version=report.draft_lock_version,
        mode=report.context_snapshot["mode"],
        status=report.status,
        is_current=current(db, application, report, settings),
        input_hash=report.input_hash,
        factors=report.context_snapshot["factors"],
        scenarios=report.scenarios,
        explanation=report.explanation,
        model_id=report.model_id,
        model_digest=report.model_digest,
        prompt_version=report.prompt_version,
        generation_config=report.generation_config,
        latency_ms=report.latency_ms,
        error_code=report.error_code,
        created_at=report.created_at,
    )


def generate(db, principal, application_id, body, auth, sources, model, session_token):
    application = client_application(db, principal.user.id, application_id)
    require_confirmation(application)  # Before checks, their cache, or a model call.
    comparison = prepare_comparison(db, principal.user.id, application_id, body, sources)
    if body.mode == "COMPARE":
        comparison = use_saved_comparison(db, application, comparison, auth.settings)
    context = build_facts(comparison, application, body.mode)
    context["basis_hash"] = basis_hash(
        db, application, payload=comparison.payload, assessment_id=comparison.assessment_id
    )
    context["assessment_id"] = str(comparison.assessment_id) if comparison.assessment_id else None
    context["fixture_stamp"] = (
        fixture_stamp(auth.settings.demo_dataset_dir) if comparison.assessment_id is None else None
    )
    context["calculation_date"] = comparison.payload["calculation_date"]
    context["policy_version"] = comparison.payload["product_snapshot"]["policy_version"]
    context["financial_months"] = deepcopy(
        comparison.payload["financial_snapshot"]["financial_months"]
    )
    context["provenance"] = comparison.response.candidates[0].provenance.model_dump(mode="json")
    context["credit_history_check_allowed"] = True
    scenarios = comparison.response.model_dump(mode="json")["candidates"]
    report_hash = canonical_hash(
        {
            "basis": context["basis_hash"],
            "candidates": [row["input_hash"] for row in scenarios],
            "mode": body.mode,
            "prompt_version": PROMPT_VERSION,
        }
    )
    revision_id = comparison.revision_id
    draft_version = comparison.response.application_version if revision_id is None else None
    user_id = principal.user.id
    # No ORM object is needed during inference. Release the connection and all read locks.
    db.rollback()
    prompt_context = {
        key: context[key] for key in ("mode", "factors", "candidate_ids", "next_step")
    }
    started = perf_counter()
    generation = model.generate(prompt_context)
    latency = max(0, round((perf_counter() - started) * 1000))
    selection = generation.selection
    error_code = generation.error_code
    if selection is not None and not valid_selection(selection, context):
        selection, error_code = None, "LLM_RESPONSE_INVALID"
    success = selection is not None and error_code is None
    if not success:
        selection = fallback_selection(context)
        error_code = error_code or "LLM_RESPONSE_INVALID"
    # Recheck session, role, membership and consent after the potentially slow call.
    principal = auth.authenticate(db, session_token)
    if principal is None or principal.user.id != user_id:
        raise APIError(401, "AUTH_REQUIRED", "Требуется повторный вход")
    if principal.user.role != "CLIENT":
        raise APIError(403, "ROLE_FORBIDDEN", "Требуется клиентская учетная запись")
    application = client_application(db, user_id, application_id, lock=True)
    require_confirmation(application)
    report = AdvisorReport(
        application_id=application_id,
        revision_id=revision_id,
        created_by_user_id=user_id,
        draft_lock_version=draft_version,
        input_hash=report_hash,
        context_snapshot=context,
        scenarios=scenarios,
        explanation=render(selection, context),
        status=ReportStatus.SUCCESS if success else ReportStatus.FALLBACK,
        model_id=generation.model_id,
        model_digest=generation.model_digest,
        prompt_version=PROMPT_VERSION,
        generation_config={
            **GENERATION_CONFIG,
            "think": False,
            "output_mode": "GROUNDED_FACT_SELECTION",
            "timeout_seconds": auth.settings.llm_timeout_seconds,
        },
        latency_ms=latency,
        error_code=error_code,
    )
    db.add(report)
    auth.activity(db, principal, commit=False)
    db.commit()
    logger.info(
        "advisor.report_created",
        extra={
            "application_id": str(application_id),
            "report_id": str(report.id),
            "revision_id": str(revision_id) if revision_id else None,
            "user_id": str(user_id),
            "report_status": report.status.value,
            "error_code": error_code,
            "duration_ms": latency,
        },
    )
    return view(db, application, report, auth.settings)


def read(db, principal, application_id, settings, report_id=None, *, bank=False):
    if bank:
        application, _ = bank_application(db, application_id)
    else:
        application = client_application(db, principal.user.id, application_id)
    require_confirmation(application)
    query = select(AdvisorReport).where(AdvisorReport.application_id == application_id)
    if bank:
        query = query.where(AdvisorReport.revision_id.is_not(None))
    if report_id is not None:
        query = query.where(AdvisorReport.id == report_id)
    report = db.scalar(
        query.order_by(AdvisorReport.created_at.desc(), AdvisorReport.id.desc()).limit(1)
    )
    if report is None:
        raise APIError(404, "ADVISOR_REPORT_NOT_FOUND", "Разбор заявки не найден")
    return view(db, application, report, settings)
