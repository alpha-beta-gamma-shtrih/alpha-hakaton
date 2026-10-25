from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from credit_cabinet.db.base import Base, IdentityMixin, UpdatedMixin, UTCDateTime
from credit_cabinet.models.enums import ApplicationStatus, DocumentSource, FormStep, Purpose
from credit_cabinet.models.types import JSON_VALUE, MONEY, RATE, enum_type


class CreditProduct(IdentityMixin, Base):
    __tablename__ = "credit_products"
    code: Mapped[str] = mapped_column(String(64))
    version: Mapped[int]
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    allowed_purposes: Mapped[list] = mapped_column(JSON_VALUE)
    min_amount = mapped_column(MONEY, nullable=False)
    max_amount = mapped_column(MONEY, nullable=False)
    min_term_months: Mapped[int]
    max_term_months: Mapped[int]
    annual_rate_percent = mapped_column(RATE, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64))
    policy_config: Mapped[dict] = mapped_column(JSON_VALUE)
    is_active: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (
        UniqueConstraint("code", "version"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "min_amount > 0 AND max_amount >= min_amount AND max_amount < 10000000000000000",
            name="amount_range",
        ),
        CheckConstraint(
            "min_term_months > 0 AND max_term_months >= min_term_months", name="term_range"
        ),
        CheckConstraint(
            "annual_rate_percent >= 0 AND annual_rate_percent < 1000", name="rate_range"
        ),
    )


class Application(IdentityMixin, UpdatedMixin, Base):
    __tablename__ = "applications"
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("credit_products.id"), index=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_type(ApplicationStatus), default=ApplicationStatus.DRAFT
    )
    requested_amount = mapped_column(MONEY, nullable=True)
    term_months: Mapped[int | None]
    purpose_code: Mapped[Purpose | None] = mapped_column(enum_type(Purpose))
    purpose_details: Mapped[str | None] = mapped_column(Text)
    draft_data: Mapped[dict] = mapped_column(
        JSON_VALUE,
        default=lambda: {
            "confirmations": {
                "data_confirmed": False,
                "credit_history_check_allowed": False,
            }
        },
    )
    ui_step: Mapped[FormStep] = mapped_column(enum_type(FormStep), default=FormStep.NEED)
    lock_version: Mapped[int] = mapped_column(default=1)
    calculation_date: Mapped[date]
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    scenario_set: Mapped[dict | None] = mapped_column(JSON_VALUE)
    signing_record: Mapped[dict | None] = mapped_column(JSON_VALUE)
    decline_record: Mapped[dict | None] = mapped_column(JSON_VALUE)
    __mapper_args__ = {"version_id_col": lock_version}
    __table_args__ = (
        CheckConstraint(
            "requested_amount > 0 AND requested_amount < 10000000000000000",
            name="positive_amount",
        ),
        CheckConstraint("term_months > 0", name="positive_term"),
        CheckConstraint("lock_version > 0", name="positive_lock_version"),
        CheckConstraint(
            "(status IN ('APPROVED', 'REJECTED', 'SIGNED') AND closed_at IS NOT NULL) OR "
            "(status NOT IN ('APPROVED', 'REJECTED', 'SIGNED') AND closed_at IS NULL)",
            name="final_closed_at",
        ),
        CheckConstraint(
            "(status = 'SIGNED' AND signing_record IS NOT NULL) OR "
            "(status <> 'SIGNED' AND signing_record IS NULL)",
            name="signing_presence",
        ),
        Index("ix_applications_company_updated", "company_id", "updated_at"),
        CheckConstraint("decline_record IS NULL OR status = 'REJECTED'", name="decline_status"),
        Index("ix_applications_bank_queue", "status", "submitted_at"),
    )


class ApplicationRevision(IdentityMixin, Base):
    __tablename__ = "application_revisions"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"))
    revision_no: Mapped[int]
    submitted_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    source_lock_version: Mapped[int]
    submission_key: Mapped[UUID]
    input_hash: Mapped[str] = mapped_column(String(64))
    requested_amount = mapped_column(MONEY, nullable=False)
    term_months: Mapped[int]
    purpose_code: Mapped[Purpose] = mapped_column(enum_type(Purpose))
    company_snapshot: Mapped[dict] = mapped_column(JSON_VALUE)
    financial_snapshot: Mapped[dict] = mapped_column(JSON_VALUE)
    product_snapshot: Mapped[dict] = mapped_column(JSON_VALUE)
    document_refs: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    schema_version: Mapped[int]
    __table_args__ = (
        UniqueConstraint("application_id", "revision_no"),
        UniqueConstraint("application_id", "submission_key"),
        UniqueConstraint("id", "application_id"),
        CheckConstraint(
            "revision_no > 0 AND source_lock_version > 0 AND schema_version > 0",
            name="positive_versions",
        ),
        CheckConstraint(
            "requested_amount > 0 AND requested_amount < 10000000000000000 AND term_months > 0",
            name="positive_terms",
        ),
    )


class Document(IdentityMixin, Base):
    __tablename__ = "documents"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    original_filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(128))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[DocumentSource] = mapped_column(enum_type(DocumentSource))
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="nonnegative_size"),)
