"""Company-wide views of existing application files and immutable signed agreements."""

from sqlalchemy import func, select

from credit_cabinet.models import Application, Document
from credit_cabinet.models.enums import ApplicationStatus
from credit_cabinet.schemas.company_files import CompanyDocumentResponse
from credit_cabinet.schemas.documents import DocumentResponse
from credit_cabinet.services.access import client_company
from credit_cabinet.services.agreements import agreement_view


def list_agreements(db, user_id, company_id, limit, offset):
    client_company(db, user_id, company_id)
    query = select(Application).where(
        Application.company_id == company_id,
        Application.archived_at.is_(None),
        Application.status == ApplicationStatus.SIGNED,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Application.updated_at.desc(), Application.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [agreement_view(db, row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def list_documents(db, user_id, company_id, limit, offset):
    client_company(db, user_id, company_id)
    query = (
        select(Document, Application.status)
        .join(Application, Application.id == Document.application_id)
        .where(Application.company_id == company_id, Application.archived_at.is_(None))
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit).offset(offset)
    )
    return {
        "items": [
            CompanyDocumentResponse(
                **DocumentResponse.model_validate(document).model_dump(exclude={"download_url"}),
                application_status=status,
            )
            for document, status in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
