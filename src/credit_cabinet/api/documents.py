import logging
from uuid import UUID

from fastapi import APIRouter, Request, Response

from credit_cabinet.api.dependencies import Authenticated, Database
from credit_cabinet.integrations.documents import DocumentStore
from credit_cabinet.schemas.errors import ErrorResponse
from credit_cabinet.services.documents import authorized_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get(
    "/{document_id}",
    response_class=Response,
    responses={
        200: {
            "description": "Проверенный синтетический CSV; cookie-сессия обязательна, CSRF для GET не нужен",
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Content-Disposition": {"schema": {"type": "string"}},
                "X-Content-SHA256": {"schema": {"type": "string"}},
            },
        },
        **{status: {"model": ErrorResponse} for status in (401, 403, 404, 422, 503)},
    },
)
def download(document_id: UUID, request: Request, db: Database, principal: Authenticated):
    """Клиент: членство в компании. Банк: ID и SHA-256 в отправленном снимке."""
    document = authorized_document(db, principal, document_id)
    # Read and verify the SAME bytes before returning; no unverified streaming or public URL.
    content = DocumentStore(request.app.state.settings).read(document)
    logger.info(
        "document.downloaded",
        extra={
            "document_id": str(document.id),
            "application_id": str(document.application_id),
            "user_id": str(principal.user.id),
            "role": principal.user.role.value,
        },
    )
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            # Server-generated UUID filename; original filename is metadata, never a header input.
            "Content-Disposition": f'attachment; filename="financial-statement-{document.id}.csv"',
            "X-Content-SHA256": document.content_sha256,
        },
    )
