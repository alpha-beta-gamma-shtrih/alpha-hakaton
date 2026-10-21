"""Application attachments and access to the exact files of submitted revisions."""

from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import select

from credit_cabinet.api.errors import APIError
from credit_cabinet.models import ApplicationRevision, Company, Document
from credit_cabinet.models.enums import Role
from credit_cabinet.schemas.documents import DocumentResponse
from credit_cabinet.services.access import find_client_application


def application_documents(db, application_id):
    return list(
        db.scalars(
            select(Document)
            .where(Document.application_id == application_id)
            .order_by(Document.created_at, Document.id)
        )
    )


def document_references(db, application_id):
    return [
        DocumentResponse.model_validate(row).model_dump(mode="json")
        for row in application_documents(db, application_id)
    ]


def ensure_documents(db, application, actor_id, store):
    """Called only by a successful write under the application's creation/row lock."""
    rows = application_documents(db, application.id)
    if rows:
        return rows
    company = db.get(Company, application.company_id)
    for template, content in store.templates(company.inn):
        document_id = uuid4()
        key = store.save(application.id, document_id, template.content_sha256, content)
        document = Document(
            id=document_id,
            application_id=application.id,
            created_by_user_id=actor_id,
            kind=template.kind,
            original_filename=PurePosixPath(template.path).name,
            mime_type="text/csv",
            storage_key=key,
            content_sha256=template.content_sha256,
            size_bytes=len(content),
            source="DEMO",
        )
        db.add(document)
    db.flush()
    return application_documents(db, application.id)


def authorized_document(db, principal, document_id):
    document = db.get(Document, document_id)
    allowed = False
    if document is not None:
        if principal.user.role == Role.CLIENT:
            allowed = (
                find_client_application(db, principal.user.id, document.application_id) is not None
            )
        elif principal.user.role == Role.BANK_STAFF:
            refs = db.scalars(
                select(ApplicationRevision.document_refs).where(
                    ApplicationRevision.application_id == document.application_id
                )
            )
            # A submitted application alone is insufficient: later draft attachments
            # stay private until a revision explicitly includes this ID and checksum.
            allowed = any(
                isinstance(ref, dict)
                and ref.get("id") == str(document.id)
                and ref.get("application_id") == str(document.application_id)
                and ref.get("content_sha256") == document.content_sha256
                for revision_refs in refs
                for ref in revision_refs
            )
    if not allowed:
        raise APIError(404, "DOCUMENT_NOT_FOUND", "Документ не найден")
    return document
