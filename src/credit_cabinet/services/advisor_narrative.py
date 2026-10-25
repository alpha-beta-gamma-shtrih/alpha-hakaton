"""Grounded, small-model-sized explanations of the user's objective and its cost."""

import re
from decimal import Decimal

from credit_cabinet.services.advisor_context import NOTICE

LABELS = {
    "REQUESTED": "Исходный запрос",
    "LOWER_AMOUNT": "Меньшая сумма",
    "LONGER_TERM": "Более долгий срок",
}
PRIORITIES = {
    "BALANCED": "Без предпочтения",
    "KEEP_AMOUNT": "Сохранить всю исходную сумму финансирования",
    "LOWER_PAYMENT": "Минимальный ежемесячный платёж",
    "LOWER_OVERPAYMENT": "Минимальная общая переплата",
}


def comparison_guidance(scenarios, priority):
    eligible = [row for row in scenarios if row["preliminary_route"] == "APPROVE"]
    if priority == "BALANCED":
        return []
    if priority == "KEEP_AMOUNT":
        eligible = [
            row
            for row in eligible
            if Decimal(row["requested_amount"]) >= Decimal(scenarios[0]["requested_amount"])
        ]
    metric = "estimated_overpayment" if priority == "LOWER_OVERPAYMENT" else "monthly_payment"
    if not eligible:
        return []
    best = min(Decimal(row[metric]) for row in eligible)
    return [row["candidate_id"] for row in eligible if Decimal(row[metric]) == best]


def prompt_context(context, scenarios, priority):
    """All branches derive from calculated routes/deltas, not a preferred scenario label."""
    base = scenarios[0]
    cards = {row["factor_id"]: row["text"] for row in context["factors"]}
    preferred = context["preferred_candidate_ids"]
    passing = any(row["preliminary_route"] == "APPROVE" for row in scenarios)
    focused = next((row for row in scenarios if row["candidate_id"] in preferred), base)
    changes = {
        field: (Decimal(str(focused[field])) > Decimal(str(base[field])))
        - (Decimal(str(focused[field])) < Decimal(str(base[field])))
        for field in ("requested_amount", "term_months", "monthly_payment", "estimated_overpayment")
    }
    validation_changes = {
        "benefit": changes if preferred else None,
        "tradeoff": changes if preferred else None,
    }
    section_labels = {}

    def facts(row):
        parts = []
        for field, label, ending in (
            ("requested_amount", "Сумма", "ой"),
            ("monthly_payment", "Ежемесячный платёж", "ого"),
            ("estimated_overpayment", "Общая переплата", "ой"),
        ):
            delta = Decimal(row[field]) - Decimal(base[field])
            parts.append(
                label
                + (
                    " меньше исходн" + ending
                    if delta < 0
                    else " больше исходн" + ending
                    if delta > 0
                    else " без изменения"
                )
            )
        return "; ".join(parts) + "."

    limited = context["next_step"]["id"] in {
        "COMPLETE_DATA",
        "RETRY_CHECK",
        "RESOLVE_RESTRICTION",
        "REVIEW_DECISION",
        "WAIT_PROCESSING",
        "CONTACT_BANK",
    }
    if context["mode"] == "EXPLAIN" or limited or not passing:
        if "MISSING_DATA" in cards:
            benefit = "Не хватает финансовой истории. Долговая нагрузка и доступность кредита пока не определены."
        else:
            reasons = base["reason_codes"]
            reason_text = {
                "COMPANY_BANKRUPTCY": "В демо-данных компании есть признак банкротства.",
                "COMPANY_NOT_ACTIVE": "Компания не имеет действующего статуса в демо-данных.",
                "CURRENT_OVERDUE": "В демо-истории есть текущая просрочка по кредитам.",
                "SEVERE_OVERDUE_HISTORY": "В демо-истории есть существенные прошлые просрочки.",
                "BUSINESS_TOO_YOUNG": "Компания работает недостаточно долго для условий демо-продукта.",
                "DEBT_LOAD_LIMIT_EXCEEDED": "Платежи с учётом нового кредита слишком велики относительно денежного потока компании.",
                "NON_POSITIVE_CASHFLOW": "Денежный поток после расходов не позволяет обслуживать новый кредит по демо-правилам.",
                "COMPANY_DATA_MISMATCH": "Сведения о компании в демо-источниках расходятся.",
                "LEGAL_STATUS_UNCONFIRMED": "Правовой статус компании не подтверждён демо-источником.",
                "RISK_SCORE_LIMIT_EXCEEDED": "По совокупности демо-факторов кредитная заявка не проходит предварительную оценку риска.",
            }
            benefit = next((reason_text[code] for code in reasons if code in reason_text), "")
            if not benefit:
                benefit = (
                    "Кредитная заявка проходит предварительные проверки. Это ещё не финальное одобрение банка."
                    if base["preliminary_route"] == "APPROVE"
                    else "Предварительная оценка кредита требует рассмотрения сотрудником банка."
                )
            if any(code.startswith("SOURCE_") for code in reasons):
                benefit = "Демо-источник проверки недоступен: это технический сбой, а не установленный отказ в кредите."
            if "SAVED_DECISION" in cards:
                benefit = cards["SAVED_DECISION"]
        tradeoff = context["next_step"]["text"]
        if context["mode"] == "EXPLAIN" and any(
            code.startswith("LOAD_") for code in base["reason_codes"]
        ):
            tradeoff = "Платежи по кредитам уже занимают часть денежного потока. Перед отправкой нужно проверить, хватит ли бюджета и на кредит, и на текущие расходы бизнеса."
        if context["mode"] == "COMPARE" and not passing:
            tradeoff = (
                "Ни один из вариантов не проходит предварительную проверку автоматически. "
                + tradeoff
            )
        subject = "Объяснение предварительной оценки и её ограничения"
    elif priority == "BALANCED":
        alternatives = scenarios[1:]
        benefit = (
            LABELS[alternatives[0]["candidate_id"]]
            + ": "
            + facts(alternatives[0])
            + (
                " Часть исходной потребности придётся финансировать самостоятельно."
                if Decimal(alternatives[0]["requested_amount"]) < Decimal(base["requested_amount"])
                else " Исходное финансирование сохраняется, но долг возвращается дольше."
            )
            if alternatives
            else "Есть только исходный уникальный вариант: " + facts(base)
        )
        tradeoff = (
            LABELS[alternatives[1]["candidate_id"]]
            + ": "
            + facts(alternatives[1])
            + " Долг придётся возвращать дольше."
            if len(alternatives) > 1
            else "Другого уникального варианта в этом наборе нет. Выбор зависит от потребности и бюджета."
        )
        subject = "Приоритет ещё не выбран. Сравнение только с исходным запросом, не между альтернативами."
        for key, row in zip(("benefit", "tradeoff"), alternatives, strict=False):
            section_labels[key] = LABELS[row["candidate_id"]]
            validation_changes[key] = {
                field: (Decimal(str(row[field])) > Decimal(str(base[field])))
                - (Decimal(str(row[field])) < Decimal(str(base[field])))
                for field in changes
            }
    elif not preferred:
        subject = PRIORITIES[priority]
        benefit = "Предварительно проходящего варианта, который сохраняет всю исходную сумму, в наборе нет."
        tradeoff = "Меньшая сумма может не покрыть потребность. Условия следует обсудить с сотрудником банка; одобрение не обещано."
    elif len(preferred) > 1:
        subject = PRIORITIES[priority]
        benefit = (
            "По выбранному критерию несколько предварительно проходящих вариантов равны: "
            + ", ".join(LABELS[key] for key in preferred)
            + "."
        )
        tradeoff = "Единственного победителя нет. Перед выбором сравните нужную сумму, срок и нагрузку на бюджет."
    else:
        subject = (
            PRIORITIES[priority] + ". Объясняем вариант «" + LABELS[focused["candidate_id"]] + "»"
        )
        benefit = (
            "Общая переплата меньше исходной, поэтому затраты на кредит ниже."
            if priority == "LOWER_OVERPAYMENT" and changes["estimated_overpayment"] < 0
            else "Ежемесячный платёж меньше исходного, это оставляет больше денег в ежемесячном бюджете."
            if changes["monthly_payment"] < 0
            else "Исходные условия соответствуют выбранному критерию среди проходящих демо-правила вариантов."
        )
        if changes["requested_amount"] == 0:
            benefit = "Вся запрошенная сумма сохраняется, а " + benefit[0].lower() + benefit[1:]
        if changes["requested_amount"] < 0:
            tradeoff = "Сумма кредита меньше нужной исходной суммы: недостающую часть финансирования придётся найти самостоятельно."
        elif changes["term_months"] > 0:
            tradeoff = "Возвращать долг придётся дольше и " + (
                "суммарно заплатить банку больше процентов."
                if changes["estimated_overpayment"] > 0
                else "общая переплата не больше исходной."
            )
        else:
            tradeoff = "Расчёт предварительный. Перед отправкой нужно сопоставить платёж с бюджетом и потребностью бизнеса."
    return {
        "mode": context["mode"],
        "priority": priority,
        "preferred_candidate_ids": preferred,
        "candidate_ids": context["candidate_ids"],
        "changes": changes if preferred and len(preferred) == 1 else None,
        "validation_changes": validation_changes,
        "section_labels": section_labels,
        "brief": {"subject": subject, "benefit": benefit, "tradeoff": tradeoff},
    }


def valid_narrative(narrative, context):
    texts = [narrative.benefit, narrative.tradeoff]
    for text in texts:
        if (
            re.search(r"[\d%₽<>]|https?://|\b(?:RUB|USD|EUR)\b", text, re.I)
            or len(re.findall(r"[а-яё]", text, re.I)) < 15
            or re.search(r"[a-z]", text, re.I)
            or re.search(
                r"(?<!не )гарантир|точно одобр|кредит одобрен|банк одобрил|без отказа|повысьте доход|скройте|поддел|выдан|одобрение обеспечено|объясни|не выбирай|дизайн|функциональн",
                text.lower(),
                re.I,
            )
        ):
            return False
    contract = context["narrative_contract"]
    text = " ".join(texts).lower()
    if "MISSING_DATA" in {row["factor_id"] for row in context["factors"]} and not re.search(
        r"нехват|не хватает|недостат|дополн|неполн", text
    ):
        return False
    # Reject common inverted comparisons. This is a bounded guard, not a proof of semantics.
    for key, section in (("benefit", narrative.benefit), ("tradeoff", narrative.tradeoff)):
        changes = contract["validation_changes"][key]
        if not changes:
            continue
        for clause in re.split(r"[.;,!?]", section.lower()):
            for field, metric in (
                ("estimated_overpayment", r"переплат"),
                ("monthly_payment", r"плат[её]ж"),
            ):
                if field == "monthly_payment" and re.search(
                    r"общ\w*\s+плат[её]ж|суммарн\w*\s+плат[её]ж", clause
                ):
                    continue
                metric = metric + r"\w*"
                direction = (
                    r"(?:больш|выш|увелич|возраст)\w*"
                    if changes[field] < 0
                    else r"(?:меньш|ниж|сниж|сокра)\w*"
                )
                bridge = (
                    r"\s+(?:(?:будет|стал|станет|становится|теперь|заметно|существенно)\s+){0,2}"
                )
                if changes[field] and re.search(
                    rf"{metric}{bridge}{direction}|{direction}\s+(?:общая\s+|ежемесячный\s+)?{metric}",
                    clause,
                ):
                    return False
            if changes["requested_amount"] == 0 and re.search(
                r"сумм(?:а|ы|у|е|ой)\b\s+(больш|меньш)|сумм(?:а|ы|у|е|ой)\b[^.;]{0,15}(увелич|уменьш)",
                clause,
            ):
                return False
        if changes["requested_amount"] == 0 and re.search(
            r"нехват.{0,20}(средств|финансирован)|недостающ.{0,25}(сумм|част|финансирован)|не покрывает",
            section.lower(),
        ):
            return False
    return True


def render_narrative(narrative, context):
    labels = context["narrative_contract"]["section_labels"]
    sections = []
    for key, text in (("benefit", narrative.benefit), ("tradeoff", narrative.tradeoff)):
        if key in labels:
            text = re.sub(r"^" + re.escape(labels[key]) + r"\s*:\s*", "", text, flags=re.I)
        sections.append(
            (labels[key] + ": " if key in labels else "") + text.strip().rstrip(".") + "."
        )
    return {
        "summary": {
            "text": " ".join(sections),
            "factor_ids": [row["factor_id"] for row in context["factors"]],
        },
        "comparisons": [],
        "next_step": context["next_step"],
        "notice": NOTICE,
    }
