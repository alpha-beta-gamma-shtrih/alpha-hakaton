from pydantic import BaseModel, Field


class FieldError(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)
    request_id: str
