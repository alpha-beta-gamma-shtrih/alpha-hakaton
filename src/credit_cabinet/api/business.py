from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from credit_cabinet.api.dependencies import Database, require_client
from credit_cabinet.models import ApplicationEvent, Company, CompanyMembership, CreditProduct
from credit_cabinet.models.enums import FinancialSource
from credit_cabinet.schemas.business import (
    CompanyDetail,
    CompanyPage,
    CompanyResponse,
    DraftCreate,
    DraftDelete,
    DraftPage,
    DraftPatch,
    DraftResponse,
    EventList,
    FinancialMonthResponse,
    ProductPage,
)
from credit_cabinet.schemas.company_files import CompanyAgreementPage, CompanyDocumentPage
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services import company_files
from credit_cabinet.services.access import client_application, client_company
from credit_cabinet.services.auth import Principal
from credit_cabinet.services.drafts import (
    archive_draft,
    create_draft,
    draft_view,
    financial_profile,
    list_drafts,
    patch_draft,
    profile_provenance,
)
from credit_cabinet.services.exposure import company_summary

Client = Annotated[Principal, Depends(require_client)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=2147483647)]

router = APIRouter(
    prefix="/api",
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)},
)


@router.get("/companies", response_model=CompanyPage, tags=["companies"])
def companies(db: Database, principal: Client, limit: Limit = 20, offset: Offset = 0):
    query = (
        select(Company)
        .join(CompanyMembership)
        .where(CompanyMembership.user_id == principal.user.id)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Company.legal_name, Company.id).limit(limit).offset(offset))
    return {"items": list(rows), "total": total, "limit": limit, "offset": offset}


@router.get("/companies/{company_id}", response_model=CompanyDetail, tags=["companies"])
def company(company_id: UUID, db: Database, principal: Client):
    row = client_company(db, principal.user.id, company_id)
    months = financial_profile(db, row.id)
    return CompanyDetail(
        credit_exposure=company_summary(db, row.id, months),
        **CompanyResponse.model_validate(row).model_dump(),
        financial_months=[FinancialMonthResponse.model_validate(month) for month in months],
        provenance=profile_provenance(
            declared=any(month.source == FinancialSource.DECLARED for month in months)
        ),
    )


@router.get(
    "/companies/{company_id}/agreements", response_model=CompanyAgreementPage, tags=["companies"]
)
def company_agreements(
    company_id: UUID, db: Database, principal: Client, limit: Limit = 20, offset: Offset = 0
):
    return company_files.list_agreements(db, principal.user.id, company_id, limit, offset)


@router.get(
    "/companies/{company_id}/documents", response_model=CompanyDocumentPage, tags=["companies"]
)
def company_documents(
    company_id: UUID, db: Database, principal: Client, limit: Limit = 20, offset: Offset = 0
):
    return company_files.list_documents(db, principal.user.id, company_id, limit, offset)


@router.get("/products", response_model=ProductPage, tags=["products"])
def products(db: Database, principal: Client, limit: Limit = 20, offset: Offset = 0):
    query = select(CreditProduct).where(
        CreditProduct.is_active.is_(True),
        CreditProduct.code == "WC_DEMO",
        CreditProduct.version.in_([2, 3]),
        CreditProduct.policy_version.in_(["demo-policy-0.2", "demo-policy-0.3"]),
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(CreditProduct.code, CreditProduct.version.desc()).limit(limit).offset(offset)
    )
    return {"items": list(rows), "total": total, "limit": limit, "offset": offset}


@router.post("/applications", response_model=DraftResponse, status_code=201, tags=["drafts"])
def create_application(body: DraftCreate, request: Request, db: Database, principal: Client):
    return create_draft(db, principal, body, request.app.state.auth)


@router.get("/applications", response_model=DraftPage, tags=["drafts"])
def applications(
    db: Database,
    principal: Client,
    limit: Limit = 20,
    offset: Offset = 0,
    company_id: UUID | None = None,
):
    return list_drafts(db, principal.user.id, limit, offset, company_id)


@router.get("/applications/{application_id}", response_model=DraftResponse, tags=["drafts"])
def application(application_id: UUID, db: Database, principal: Client):
    row = client_application(db, principal.user.id, application_id)
    return draft_view(row, db.get(CreditProduct, row.product_id), db)


@router.patch("/applications/{application_id}", response_model=DraftResponse, tags=["drafts"])
def save_application(
    application_id: UUID,
    body: DraftPatch,
    request: Request,
    db: Database,
    principal: Client,
):
    return patch_draft(db, principal, application_id, body, request.app.state.auth)


@router.get("/applications/{application_id}/events", response_model=EventList, tags=["drafts"])
def events(application_id: UUID, db: Database, principal: Client):
    client_application(db, principal.user.id, application_id)
    rows = db.scalars(
        select(ApplicationEvent)
        .where(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.visibility == "CLIENT",
        )
        .order_by(ApplicationEvent.sequence_no)
    )
    return {"items": list(rows)}


@router.delete("/applications/{application_id}", status_code=204, tags=["drafts"])
def delete_application(
    application_id: UUID,
    body: DraftDelete,
    request: Request,
    db: Database,
    principal: Client,
):
    archive_draft(db, principal, application_id, body.expected_version, request.app.state.auth)
    return Response(status_code=204)
