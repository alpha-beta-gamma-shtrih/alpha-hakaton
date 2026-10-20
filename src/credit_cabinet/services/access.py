from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import Application, Company, CompanyMembership, User
from credit_cabinet.models.enums import ApplicationStatus, FormStep, Role


def client_company(db: Session, user_id: UUID, company_id: UUID) -> Company:
    company = db.scalar(
        select(Company)
        .join(CompanyMembership, CompanyMembership.company_id == Company.id)
        .where(CompanyMembership.user_id == user_id, Company.id == company_id)
    )
    if company is None:
        raise APIError(404, "COMPANY_NOT_FOUND", "Компания не найдена")
    return company


def find_client_application(db: Session, user_id: UUID, application_id: UUID, *, lock=False):
    query = (
        select(Application)
        .join(
            CompanyMembership,
            CompanyMembership.company_id == Application.company_id,
        )
        .where(CompanyMembership.user_id == user_id, Application.id == application_id)
    )
    if lock:
        query = query.with_for_update(of=Application)
    return db.scalar(query)


def client_application(db: Session, user_id: UUID, application_id: UUID, *, lock=False):
    application = find_client_application(db, user_id, application_id, lock=lock)
    if application is None:
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена")
    return application


def safe_ui_context(db: Session, user: User) -> dict:
    context = user.ui_context or {}
    result = {}
    sections = {"overview", "applications"} if user.role == Role.CLIENT else {"overview", "bank"}
    if context.get("section") in sections:
        result["section"] = context["section"]
    if user.role != Role.CLIENT:
        return result
    if context.get("step") in {step.value for step in FormStep}:
        result["step"] = context["step"]
    raw_id = context.get("last_application_id")
    if raw_id is not None:
        try:
            application_id = UUID(str(raw_id))
        except (ValueError, TypeError):
            return {"section": "overview"}
        application = find_client_application(db, user.id, application_id)
        if application is None:
            return {"section": "overview"}
        result["last_application_id"] = str(application.id)
        # Future final statuses should open the result, not an editable form.
        if application.status == ApplicationStatus.DRAFT:
            result["step"] = application.ui_step.value
        else:
            result.pop("step", None)
    return result
