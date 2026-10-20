from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from credit_cabinet.db.base import Base, IdentityMixin
from credit_cabinet.models.enums import ApplicationStatus, EventType, ReportStatus, Visibility
from credit_cabinet.models.types import JSON_VALUE, enum_type


class ApplicationEvent(IdentityMixin, Base):
    __tablename__ = "application_events"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"))
    revision_id: Mapped[UUID | None]
    sequence_no: Mapped[int]
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[EventType] = mapped_column(enum_type(EventType))
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        enum_type(ApplicationStatus, "from_status")
    )
    to_status: Mapped[ApplicationStatus | None] = mapped_column(
        enum_type(ApplicationStatus, "to_status")
    )
    visibility: Mapped[Visibility] = mapped_column(enum_type(Visibility))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    __table_args__ = (
        UniqueConstraint("application_id", "sequence_no"),
        CheckConstraint("sequence_no > 0", name="positive_sequence_no"),
        ForeignKeyConstraint(
            ["revision_id", "application_id"],
            ["application_revisions.id", "application_revisions.application_id"],
        ),
        Index("ix_application_events_revision_id", "revision_id"),
    )


class AdvisorReport(IdentityMixin, Base):
    __tablename__ = "advisor_reports"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"))
    revision_id: Mapped[UUID | None]
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    draft_lock_version: Mapped[int | None]
    input_hash: Mapped[str] = mapped_column(String(64))
    context_snapshot: Mapped[dict] = mapped_column(JSON_VALUE)
    scenarios: Mapped[list] = mapped_column(JSON_VALUE)
    explanation: Mapped[dict | None] = mapped_column(JSON_VALUE)
    status: Mapped[ReportStatus] = mapped_column(enum_type(ReportStatus))
    model_id: Mapped[str | None] = mapped_column(Text)
    model_digest: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(64))
    generation_config: Mapped[dict] = mapped_column(JSON_VALUE)
    latency_ms: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "application_id"],
            ["application_revisions.id", "application_revisions.application_id"],
        ),
        Index("ix_advisor_reports_revision_id", "revision_id"),
        Index("ix_advisor_reports_context", "application_id", "input_hash", "created_at"),
        CheckConstraint(
            "(revision_id IS NOT NULL AND draft_lock_version IS NULL) OR "
            "(revision_id IS NULL AND draft_lock_version > 0 AND draft_lock_version IS NOT NULL)",
            name="report_context",
        ),
        CheckConstraint("latency_ms >= 0", name="nonnegative_latency"),
    )
