from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field

from credit_cabinet.models.enums import DocumentSource


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    kind: str
    original_filename: str
    mime_type: str
    content_sha256: str
    size_bytes: int
    source: DocumentSource
    created_at: datetime

    @computed_field
    @property
    def download_url(self) -> str:
        return f"/api/documents/{self.id}"
