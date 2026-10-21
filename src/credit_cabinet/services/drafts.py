import logging
from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from credit_cabinet.api.errors import APIError
from credit_cabinet.core.demo import CALCULATION_DATE, FINANCIAL_AS_OF_DATE, FINANCIAL_MONTHS
from credit_cabinet.core.security import utc_now
from credit_cabinet.integrations.documents import DocumentStore
from credit_cabinet.models import (
    Application,
    ApplicationEvent,
    CompanyFinancialMonth,
    CompanyMembership,
    CreditProduct,
)
from credit_cabinet.models.enums import ApplicationStatus, FinancialSource, FormStep
from credit_cabinet.schemas.business import DraftCreate, DraftPatch, DraftResponse
from credit_cabinet.services.access import client_application, client_company
from credit_cabinet.services.auth import AuthService, Principal
from credit_cabinet.services.documents import document_references, ensure_documents
from credit_cabinet.services.views import enrich_application

logger = logging.getLogger(__name__)


def profile_provenance(*, declared=False) -> dict:
    return {
        "company": {
            "source": "DEMO_PROFILE",
            "as_of_date": CALCULATION_DATE.isoformat(),
            "checked_at": None,
        },
        "financial_months": {
            "source": "CLIENT_DECLARED" if declared else "DEMO_PROFILE",
            "as_of_date": FINANCIAL_AS_OF_DATE.isoformat(),
            "checked_at": None,
        },
        "credit_history": None,
    }


def financial_profile(db: Session, company_id: UUID):
    return list(
        db.scalars(
            select(CompanyFinancialMonth)
            .where(
                CompanyFinancialMonth.company_id == company_id,
                CompanyFinancialMonth.month.in_(FINANCIAL_MONTHS),
            )
            .order_by(CompanyFinancialMonth.month)
        )
    )


def remember_draft(principal: Principal, application: Application):
    principal.user.ui_context = {
        "section": "applications",
        "last_application_id": str(application.id),
        "step": application.ui_step.value,
    }


def draft_view(application: Application, product: CreditProduct, db: Session) -> DraftResponse:
    data = deepcopy(application.draft_data)
    provenance = data.pop("provenance", profile_provenance())
    # Draft provenance stays separate from the checks of its submitted revision.
    provenance["credit_history"] = None
    response = DraftResponse(
        documents=document_references(db, application.id),
        id=application.id,
        company_id=application.company_id,
        product_id=application.product_id,
        status=application.status,
        version=application.lock_version,
        requested_amount=application.requested_amount,
        term_months=application.term_months,
        purpose_code=application.purpose_code,
        purpose_details=application.purpose_details,
        draft_data=data,
        ui_step=application.ui_step,
        calculation_date=application.calculation_date,
        policy_version=product.policy_version,
        provenance=provenance,
        allowed_actions=(["EDIT_DRAFT", "SUBMIT"] if product.is_active else ["EDIT_DRAFT"])
        if application.status in (ApplicationStatus.DRAFT, ApplicationStatus.NEEDS_INFO)
        else [],
        created_at=application.created_at,
        updated_at=application.updated_at,
    )
    return enrich_application(db, application, response)


def create_draft(
    db: Session, principal: Principal, body: DraftCreate, auth: AuthService
) -> DraftResponse:
    client_company(db, principal.user.id, body.company_id)
    product = db.scalar(
        select(CreditProduct).where(
            CreditProduct.id == body.product_id,
            CreditProduct.is_active.is_(True),
            CreditProduct.code == "WC_DEMO",
            CreditProduct.version == 2,
            CreditProduct.policy_version == "demo-policy-0.2",
        )
    )
    if product is None:
        raise APIError(404, "PRODUCT_NOT_FOUND", "Доступная версия продукта не найдена")
    months = financial_profile(db, body.company_id)
    application = Application(
        company_id=body.company_id,
        created_by_user_id=principal.user.id,
        product_id=product.id,
        status=ApplicationStatus.DRAFT,
        ui_step=FormStep.NEED,
        calculation_date=CALCULATION_DATE,
        draft_data={
            "financial_months": [
                {
                    "month": row.month.isoformat(),
                    "cash_inflow": format(row.cash_inflow, ".2f"),
                    "operating_outflow": format(row.operating_outflow, ".2f"),
                    "existing_debt_payment": format(row.existing_debt_payment, ".2f"),
                }
                for row in months
            ],
            "confirmations": {"data_confirmed": False, "credit_history_check_allowed": False},
            "info_response": None,
            "provenance": profile_provenance(
                declared=any(row.source == FinancialSource.DECLARED for row in months)
            ),
        },
    )
    db.add(application)
    db.flush()
    ensure_documents(db, application, principal.user.id, DocumentStore(auth.settings))
    db.add(
        ApplicationEvent(
            application_id=application.id,
            sequence_no=1,
            actor_user_id=principal.user.id,
            event_type="DRAFT_CREATED",
            from_status=None,
            to_status="DRAFT",
            visibility="CLIENT",
            message="Создан черновик заявки",
            details={},
        )
    )
    remember_draft(principal, application)
    auth.activity(db, principal, commit=False)
    db.commit()
    logger.info(
        "application.draft_created",
        extra={
            "application_id": str(application.id),
            "user_id": str(principal.user.id),
            "version": application.lock_version,
        },
    )
    return draft_view(application, product, db)


def patch_draft(
    db: Session, principal: Principal, application_id: UUID, body: DraftPatch, auth: AuthService
):
    application = client_application(db, principal.user.id, application_id, lock=True)
    if application.status not in (ApplicationStatus.DRAFT, ApplicationStatus.NEEDS_INFO):
        raise APIError(
            409, "APPLICATION_NOT_EDITABLE", "Заявка недоступна для редактирования черновика"
        )
    if application.lock_version != body.expected_version:
        raise APIError(409, "VERSION_CONFLICT", "Черновик уже изменён. Получите актуальную версию")
    for field in ("requested_amount", "term_months", "purpose_code", "purpose_details", "ui_step"):
        if field in body.model_fields_set:
            setattr(application, field, getattr(body, field))
    data = deepcopy(application.draft_data)
    if "draft_data" in body.model_fields_set:
        patch = body.draft_data
        if "financial_months" in patch.model_fields_set:
            data["financial_months"] = [
                row.model_dump(mode="json")
                for row in sorted(patch.financial_months, key=lambda row: row.month)
            ]
            provenance = deepcopy(data.get("provenance", profile_provenance()))
            provenance["financial_months"] = profile_provenance(declared=True)["financial_months"]
            data["provenance"] = provenance
        if "confirmations" in patch.model_fields_set:
            data["confirmations"] = {
                **data.get("confirmations", {}),
                **patch.confirmations.model_dump(exclude_unset=True),
            }
        if "info_response" in patch.model_fields_set:
            data["info_response"] = patch.info_response
    application.draft_data = data
    application.lock_version += 1
    application.updated_at = utc_now()
    remember_draft(principal, application)
    try:
        auth.activity(db, principal, commit=False)
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(
            409, "VERSION_CONFLICT", "Черновик уже изменён. Получите актуальную версию"
        ) from None
    product = db.get(CreditProduct, application.product_id)
    logger.info(
        "application.draft_saved",
        extra={
            "application_id": str(application.id),
            "user_id": str(principal.user.id),
            "version": application.lock_version,
        },
    )
    return draft_view(application, product, db)


def list_drafts(db: Session, user_id: UUID, limit: int, offset: int, company_id: UUID | None):
    if company_id is not None:
        client_company(db, user_id, company_id)
    filters = [CompanyMembership.user_id == user_id]
    if company_id:
        filters.append(Application.company_id == company_id)
    query = (
        select(Application, CreditProduct)
        .join(
            CompanyMembership,
            CompanyMembership.company_id == Application.company_id,
        )
        .join(CreditProduct, CreditProduct.id == Application.product_id)
        .where(*filters)
    )
    total = db.scalar(
        select(func.count()).select_from(
            select(Application.id)
            .join(CompanyMembership, CompanyMembership.company_id == Application.company_id)
            .where(*filters)
            .subquery()
        )
    )
    rows = db.execute(
        query.order_by(Application.updated_at.desc(), Application.id).limit(limit).offset(offset)
    ).all()
    return {
        "items": [draft_view(application, product, db) for application, product in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
