"""Backend facts and currentness; no client prose, credentials or internal bank comments."""

import hashlib
from decimal import Decimal

from sqlalchemy import select

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import Decision
from credit_cabinet.models.enums import ApplicationStatus
from credit_cabinet.schemas.advisor import ModelSelection
from credit_cabinet.services.policy import canonical_hash
from credit_cabinet.services.scenarios import revision_payload
from credit_cabinet.services.snapshots import application_input, financial_input_hash
from credit_cabinet.services.submissions import latest_assessment, latest_revision

EDITABLE = {ApplicationStatus.DRAFT, ApplicationStatus.NEEDS_INFO}
NOTICE = "Демонстрационный разбор: не гарантирует одобрение или выдачу. Числа, предварительные проверки и подбор по приоритету рассчитаны backend. Модель объясняет компромиссы и может ошибаться; сверяйте текст с карточками вариантов."
ROUTES = {
    "APPROVE": "Проходит предварительные демо-правила",
    "REJECT": "Не проходит текущие демо-правила",
    "NEEDS_INFO": "Нужно дополнить данные",
    "MANUAL_REVIEW": "Потребуется рассмотрение специалиста",
}
NEXT_STEPS = {
    "REVIEW_SUBMISSION": "Проверьте сведения и отдельно отправьте заявку. Разбор сам ее не отправляет.",
    "REVIEW_PARAMETERS": "Сравните сумму и срок; выбранные параметры сохраните отдельным действием в форме.",
    "COMPLETE_DATA": "Дополните указанные поля и сохраните форму; после дозапроса нужна новая отправка.",
    "WAIT_PROCESSING": "Отправка сохранена; дождитесь обработки или обратитесь к сотруднику для технического повтора.",
    "CONTACT_BANK": "Заявка у сотрудника; следите за статусом и возможным дозапросом.",
    "REVIEW_DECISION": "Посмотрите сохраненное решение по отправленной версии; сравнение не меняет его.",
    "RESOLVE_RESTRICTION": "Уточните причину ограничения у сотрудника банка. Одно изменение суммы или срока не устраняет ограничения по статусу компании или просрочкам.",
    "RETRY_CHECK": "Проверка источника недоступна; повторите её позже. Технический сбой сам по себе не означает отказ.",
}


def require_confirmation(application):
    if (
        application.draft_data.get("confirmations", {}).get("credit_history_check_allowed")
        is not True
    ):
        raise APIError(
            422,
            "CREDIT_HISTORY_CONFIRMATION_REQUIRED",
            "Подтвердите демонстрационную проверку кредитной истории",
            fields=[
                {
                    "field": "draft_data.confirmations.credit_history_check_allowed",
                    "message": "Требуется явное подтверждение",
                }
            ],
        )


def basis_hash(db, application, *, payload=None, assessment_id=None):
    revision = latest_revision(db, application.id)
    if payload is None:
        payload = (
            revision_payload(revision)
            if revision and application.status not in EDITABLE
            else application_input(db, application, require_confirmation=False)
        )
        assessment = latest_assessment(db, revision.id) if revision else None
        assessment_id = assessment.id if assessment else None
    decision = db.scalar(select(Decision).where(Decision.application_id == application.id))
    return financial_input_hash(
        {
            "input": payload,
            "assessment_id": str(assessment_id) if assessment_id else None,
            "latest_revision_id": str(revision.id) if revision else None,
            "status": application.status.value,
            "decision": {"id": str(decision.id), "outcome": decision.outcome.value}
            if decision
            else None,
        }
    )


def fixture_stamp(directory):
    """Local input fingerprint only; never invokes checks or consumes fixture attempts."""
    hashes = {}
    for name in ("manifest.json", "companies.csv", "fns_responses.json", "bki_responses.json"):
        try:
            with (directory / name).open("rb") as file:
                content = file.read(2 * 1024 * 1024 + 1)
            hashes[name] = hashlib.sha256(content).hexdigest()
        except OSError:
            hashes[name] = "UNAVAILABLE"
    return canonical_hash(hashes)


def build_facts(comparison, application, mode):
    candidates = comparison.response.model_dump(mode="json")["candidates"]
    cards = []

    def card(factor_id, text, candidate_id=None):
        cards.append({"factor_id": factor_id, "candidate_id": candidate_id, "text": text})

    declared = (
        comparison.payload["financial_snapshot"]["provenance"]["financial_months"]["source"]
        == "CLIENT_DECLARED"
    )
    card(
        "DATA_ORIGIN",
        "Финансы заявлены клиентом и не подтверждены банком; проверки используют синтетические источники."
        if declared
        else "Финансы взяты из синтетического демо-профиля; проверки также демонстрационные.",
    )
    card("PRELIMINARY_ONLY", "Сравнение не является решением банка и не изменяет заявку.")
    if application.status in (
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.SIGNED,
    ):
        card(
            "SAVED_DECISION",
            "По отправленной версии уже сохранено решение: "
            + (
                "одобрено."
                if application.status in (ApplicationStatus.APPROVED, ApplicationStatus.SIGNED)
                else "отказано."
            )
            + " Предварительные варианты его не заменяют.",
        )
    for candidate in candidates:
        identifier = candidate["candidate_id"]
        card(
            identifier + "_PAYMENT",
            f"Сумма {candidate['requested_amount']} RUB, срок {candidate['term_months']} мес., ставка {candidate['annual_rate_percent']}% годовых; платеж {candidate['monthly_payment']} RUB в месяц, расчетная переплата {candidate['estimated_overpayment']} RUB.",
            identifier,
        )
        pricing = candidate.get("pricing", {})
        if pricing.get("status") == "PERSONALIZED":
            components = [
                f"{r['label']}: +{r['percentage_points']} п. п." for r in pricing["additions"]
            ]
            components += [
                f"{r['label']}: скидка {r['percentage_points']} п. п." for r in pricing["discounts"]
            ]
            card(
                identifier + "_PRICING",
                f"Базовая ставка {pricing['base_rate_percent']}%. "
                + "; ".join(components)
                + f". Фактически применённая скидка {pricing['applied_discount_pp']} п. п.; минимальная ставка {pricing['minimum_rate_percent']}%, итог {pricing['annual_rate_percent']}%. Цель и партнёрская покупка не подтверждены документами в DEMO.",
                identifier,
            )
        elif pricing.get("status") == "INDICATIVE":
            card(
                identifier + "_PRICING",
                "Персональная ставка не определена: недостаточно подтверждённых демо-данных. Платёж показан ориентировочно по базовой ставке.",
                identifier,
            )
        route = candidate["preliminary_route"]
        card(
            identifier + "_ROUTE",
            ROUTES.get(route, "Оценка недоступна")
            + ". "
            + " ".join(row["message"] for row in candidate["reasons"]),
            identifier,
        )
        if candidate["load_ratio"] is not None:
            score = (
                f"Риск-балл {candidate['risk_score']}."
                if candidate["risk_score"] is not None
                else "Риск-балл не рассчитывался."
            )
            card(
                identifier + "_LOAD",
                f"Демонстрационная долговая нагрузка: {Decimal(candidate['load_ratio']) * 100:.2f}%. {score}",
                identifier,
            )
        if identifier != "REQUESTED":
            original = candidates[0]
            saving = Decimal(original["monthly_payment"]) - Decimal(candidate["monthly_payment"])
            difference = Decimal(candidate["estimated_overpayment"]) - Decimal(
                original["estimated_overpayment"]
            )
            card(
                identifier + "_TRADEOFF",
                f"По сравнению с исходным запросом ежемесячный платеж меньше на {saving:.2f} RUB; изменение расчетной переплаты {difference:+.2f} RUB. "
                + (
                    "Доступная сумма меньше."
                    if identifier == "LOWER_AMOUNT"
                    else "Срок возврата длиннее."
                ),
                identifier,
            )
    if comparison.missing_fields:
        card("MISSING_DATA", "Нужно дополнить поля: " + ", ".join(comparison.missing_fields) + ".")
    next_step = {
        ApplicationStatus.SUBMITTED: "WAIT_PROCESSING",
        ApplicationStatus.NEEDS_INFO: "COMPLETE_DATA",
        ApplicationStatus.MANUAL_REVIEW: "CONTACT_BANK",
        ApplicationStatus.APPROVED: "REVIEW_DECISION",
        ApplicationStatus.REJECTED: "REVIEW_DECISION",
        ApplicationStatus.SIGNED: "REVIEW_DECISION",
    }.get(application.status)
    if next_step is None:
        reasons = candidates[0]["reason_codes"]
        next_step = (
            "COMPLETE_DATA"
            if comparison.missing_fields
            else "RETRY_CHECK"
            if any(code.startswith("SOURCE_") for code in reasons)
            else "RESOLVE_RESTRICTION"
            if set(reasons)
            & {
                "COMPANY_NOT_ACTIVE",
                "COMPANY_BANKRUPTCY",
                "BUSINESS_TOO_YOUNG",
                "CURRENT_OVERDUE",
                "SEVERE_OVERDUE_HISTORY",
                "LEGAL_STATUS_UNCONFIRMED",
                "COMPANY_DATA_MISMATCH",
            }
            else "REVIEW_SUBMISSION"
            if candidates[0]["preliminary_route"] == "APPROVE"
            else "REVIEW_PARAMETERS"
        )
    return {
        "mode": mode,
        "factors": cards,
        "candidate_ids": [row["candidate_id"] for row in candidates],
        "next_step": {"id": next_step, "text": NEXT_STEPS[next_step]},
    }


def fallback_selection(context):
    available = {row["factor_id"] for row in context["factors"]}
    summary = [
        row
        for row in (
            "DATA_ORIGIN",
            "SAVED_DECISION",
            "MISSING_DATA",
            "REQUESTED_ROUTE",
            "REQUESTED_PAYMENT",
        )
        if row in available
    ][:4]
    return ModelSelection(
        summary_factor_ids=summary,
        comparisons=[
            {
                "candidate_id": identifier,
                "factor_ids": [
                    identifier + "_PAYMENT",
                    identifier + "_TRADEOFF"
                    if identifier != "REQUESTED"
                    else identifier + "_ROUTE",
                ],
            }
            for identifier in context["candidate_ids"]
        ]
        if context["mode"] == "COMPARE"
        else [],
        next_step_id=context["next_step"]["id"],
    )


def render(selection, context):
    facts = {row["factor_id"]: row["text"] for row in context["factors"]}

    def section(ids):
        return {"factor_ids": ids, "text": " ".join(facts[key] for key in ids)}

    return {
        "summary": section(selection.summary_factor_ids),
        "comparisons": [
            {"candidate_id": row.candidate_id, **section(row.factor_ids)}
            for row in selection.comparisons
        ],
        "next_step": context["next_step"],
        "notice": NOTICE,
    }
