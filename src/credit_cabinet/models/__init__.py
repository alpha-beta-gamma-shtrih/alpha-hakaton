"""Import every model so Alembic sees complete metadata."""

from credit_cabinet.models.applications import (
    Application,
    ApplicationRevision,
    CreditProduct,
    Document,
)
from credit_cabinet.models.history import AdvisorReport, ApplicationEvent
from credit_cabinet.models.identity import (
    AuthSession,
    Company,
    CompanyFinancialMonth,
    CompanyMembership,
    User,
)
from credit_cabinet.models.processing import Assessment, CheckResult, Decision, InformationRequest

__all__ = [
    "AdvisorReport",
    "Application",
    "ApplicationEvent",
    "ApplicationRevision",
    "Assessment",
    "AuthSession",
    "CheckResult",
    "Company",
    "CompanyFinancialMonth",
    "CompanyMembership",
    "CreditProduct",
    "Decision",
    "Document",
    "InformationRequest",
    "User",
]
