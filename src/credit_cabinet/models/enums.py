from enum import StrEnum


class Role(StrEnum):
    CLIENT = "CLIENT"
    BANK_STAFF = "BANK_STAFF"


class LegalForm(StrEnum):
    IP = "IP"
    OOO = "OOO"


class FinancialSource(StrEnum):
    DEMO = "DEMO"
    DECLARED = "DECLARED"


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHECKING = "CHECKING"
    NEEDS_INFO = "NEEDS_INFO"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FormStep(StrEnum):
    NEED = "NEED"
    COMPANY = "COMPANY"
    FINANCES = "FINANCES"
    REVIEW = "REVIEW"


class Purpose(StrEnum):
    INVENTORY = "INVENTORY"
    OPERATING_EXPENSES = "OPERATING_EXPENSES"
    SEASONAL_PURCHASE = "SEASONAL_PURCHASE"


class RiskBand(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class Routing(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NEEDS_INFO = "NEEDS_INFO"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CheckSource(StrEnum):
    DATA_QUALITY = "DATA_QUALITY"
    FNS = "FNS"
    BKI = "BKI"


class CheckStatus(StrEnum):
    SUCCESS = "SUCCESS"
    NO_DATA = "NO_DATA"
    ERROR = "ERROR"


class DecisionSource(StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class DecisionOutcome(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InfoStatus(StrEnum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"


class Visibility(StrEnum):
    CLIENT = "CLIENT"
    BANK = "BANK"


class ReportStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"


class DocumentSource(StrEnum):
    DEMO = "DEMO"
    UPLOAD = "UPLOAD"


class EventType(StrEnum):
    DRAFT_CREATED = "DRAFT_CREATED"
    DRAFT_ARCHIVED = "DRAFT_ARCHIVED"
    SUBMITTED = "SUBMITTED"
    CHECKS_COMPLETED = "CHECKS_COMPLETED"
    INFO_REQUESTED = "INFO_REQUESTED"
    INFO_ANSWERED = "INFO_ANSWERED"
    DECISION_MADE = "DECISION_MADE"
    PROCESSING_RETRIED = "PROCESSING_RETRIED"
