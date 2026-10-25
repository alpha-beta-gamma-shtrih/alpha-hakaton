from credit_cabinet.models.enums import ApplicationStatus
from credit_cabinet.schemas.agreements import AgreementResponse
from credit_cabinet.schemas.business import SignatureResponse, StrictModel
from credit_cabinet.schemas.documents import DocumentResponse


class SignedAgreementResponse(AgreementResponse):
    signature: SignatureResponse


class CompanyAgreementPage(StrictModel):
    items: list[SignedAgreementResponse]
    total: int
    limit: int
    offset: int


class CompanyDocumentResponse(DocumentResponse):
    application_status: ApplicationStatus


class CompanyDocumentPage(StrictModel):
    items: list[CompanyDocumentResponse]
    total: int
    limit: int
    offset: int
