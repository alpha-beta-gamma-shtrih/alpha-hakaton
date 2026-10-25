from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from credit_cabinet.db.base import Base, IdentityMixin, UTCDateTime
from credit_cabinet.models.enums import (
    CheckSource,
    CheckStatus,
    DecisionOutcome,
    DecisionSource,
    InfoStatus,
    RiskBand,
    Routing,
)
from credit_cabinet.models.types import JSON_VALUE, MONEY, RATE, enum_type


class Assessment(IdentityMixin, Base):
    __tablename__ = "assessments"
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("application_revisions.id"))
    run_no: Mapped[int]
    rules_version: Mapped[str] = mapped_column(String(64))
    input_facts: Mapped[dict] = mapped_column(JSON_VALUE)
    risk_score: Mapped[int | None]
    risk_band: Mapped[RiskBand] = mapped_column(enum_type(RiskBand))
    routing: Mapped[Routing] = mapped_column(enum_type(Routing))
    reason_codes: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    calculation_details: Mapped[dict] = mapped_column(JSON_VALUE)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("revision_id", "run_no"),
        UniqueConstraint("id", "revision_id"),
        CheckConstraint("run_no > 0", name="positive_run_no"),
        CheckConstraint("risk_score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint(
            "(risk_score IS NULL AND risk_band = 'UNKNOWN') OR "
            "(risk_score IS NOT NULL AND risk_band <> 'UNKNOWN')",
            name="known_score",
        ),
        CheckConstraint("completed_at >= started_at", name="time_order"),
    )


class CheckResult(IdentityMixin, Base):
    __tablename__ = "check_results"
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("assessments.id"))
    source: Mapped[CheckSource] = mapped_column(enum_type(CheckSource))
    status: Mapped[CheckStatus] = mapped_column(enum_type(CheckStatus))
    normalized_data: Mapped[dict | None] = mapped_column(JSON_VALUE)
    reason_codes: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64))
    source_version: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (
        UniqueConstraint("assessment_id", "source"),
        CheckConstraint("completed_at >= started_at", name="time_order"),
        CheckConstraint(
            "(status = 'SUCCESS' AND normalized_data IS NOT NULL) OR "
            "(status IN ('ERROR', 'NO_DATA') AND normalized_data IS NULL)",
            name="result_data",
        ),
    )


class Decision(IdentityMixin, Base):
    __tablename__ = "decisions"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), unique=True)
    revision_id: Mapped[UUID]
    assessment_id: Mapped[UUID]
    source: Mapped[DecisionSource] = mapped_column(enum_type(DecisionSource))
    decided_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    outcome: Mapped[DecisionOutcome] = mapped_column(enum_type(DecisionOutcome))
    approved_amount = mapped_column(MONEY, nullable=True)
    approved_term_months: Mapped[int | None]
    annual_rate_percent = mapped_column(RATE, nullable=True)
    monthly_payment = mapped_column(MONEY, nullable=True)
    offer_snapshot: Mapped[dict | None] = mapped_column(JSON_VALUE, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON_VALUE)
    public_explanation: Mapped[str] = mapped_column(Text)
    internal_comment: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "application_id"],
            ["application_revisions.id", "application_revisions.application_id"],
        ),
        ForeignKeyConstraint(
            ["assessment_id", "revision_id"], ["assessments.id", "assessments.revision_id"]
        ),
        Index("ix_decisions_revision_id", "revision_id"),
        Index("ix_decisions_assessment_id", "assessment_id"),
        CheckConstraint(
            "(source = 'AUTO' AND decided_by_user_id IS NULL) OR "
            "(source = 'MANUAL' AND decided_by_user_id IS NOT NULL)",
            name="decision_actor",
        ),
        CheckConstraint(
            "(outcome = 'APPROVED' AND approved_amount IS NOT NULL AND "
            "approved_term_months IS NOT NULL AND annual_rate_percent IS NOT NULL AND "
            "monthly_payment IS NOT NULL) OR "
            "(outcome = 'REJECTED' AND approved_amount IS NULL AND approved_term_months IS NULL "
            "AND annual_rate_percent IS NULL AND monthly_payment IS NULL)",
            name="offer_presence",
        ),
        CheckConstraint(
            "approved_amount > 0 AND approved_amount < 10000000000000000 AND "
            "approved_term_months > 0 AND annual_rate_percent >= 0 AND annual_rate_percent < 1000 "
            "AND monthly_payment > 0 AND monthly_payment < 10000000000000000",
            name="offer_values",
        ),
    )


class InformationRequest(IdentityMixin, Base):
    __tablename__ = "information_requests"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"))
    revision_id: Mapped[UUID]
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    requested_fields: Mapped[list] = mapped_column(JSON_VALUE)
    message_to_client: Mapped[str] = mapped_column(Text)
    status: Mapped[InfoStatus] = mapped_column(enum_type(InfoStatus), default=InfoStatus.OPEN)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answered_revision_id: Mapped[UUID | None]
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "application_id"],
            ["application_revisions.id", "application_revisions.application_id"],
        ),
        ForeignKeyConstraint(
            ["answered_revision_id", "application_id"],
            ["application_revisions.id", "application_revisions.application_id"],
        ),
        Index("ix_information_requests_revision_id", "revision_id"),
        Index("ix_information_requests_answered_revision_id", "answered_revision_id"),
        Index(
            "uq_information_requests_open_application",
            "application_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
        CheckConstraint(
            "(status = 'OPEN' AND answered_at IS NULL AND answered_revision_id IS NULL) OR "
            "(status = 'ANSWERED' AND answered_at IS NOT NULL AND answered_revision_id IS NOT NULL)",
            name="answer_presence",
        ),
        CheckConstraint(
            "answered_revision_id IS NULL OR answered_revision_id <> revision_id",
            name="answer_new_revision",
        ),
    )
