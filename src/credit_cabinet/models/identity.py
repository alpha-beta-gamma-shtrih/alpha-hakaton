from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    extract,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from credit_cabinet.db.base import Base, IdentityMixin, UpdatedMixin, UTCDateTime
from credit_cabinet.models.enums import FinancialSource, LegalForm, Role
from credit_cabinet.models.types import JSON_VALUE, MONEY, enum_type


class User(IdentityMixin, UpdatedMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(enum_type(Role))
    is_active: Mapped[bool] = mapped_column(default=True)
    ui_context: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    __table_args__ = (CheckConstraint("email = lower(trim(email))", name="normalized_email"),)


class AuthSession(IdentityMixin, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime())
    absolute_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    idle_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        CheckConstraint(
            "created_at <= last_activity_at AND last_activity_at <= idle_expires_at "
            "AND idle_expires_at <= absolute_expires_at",
            name="session_time_order",
        ),
    )


class Company(IdentityMixin, UpdatedMixin, Base):
    __tablename__ = "companies"
    legal_name: Mapped[str] = mapped_column(Text)
    legal_form: Mapped[LegalForm] = mapped_column(enum_type(LegalForm))
    inn: Mapped[str] = mapped_column(String(12), unique=True)
    registration_number: Mapped[str | None] = mapped_column(String(15))
    registered_on: Mapped[date]
    okved_code: Mapped[str] = mapped_column(String(16))
    region_code: Mapped[str] = mapped_column(String(8))
    business_description: Mapped[str | None] = mapped_column(Text)
    has_active_loan_in_our_bank: Mapped[bool] = mapped_column(default=False, server_default=false())
    __table_args__ = (
        CheckConstraint(
            "(legal_form = 'IP' AND length(inn) = 12) OR (legal_form = 'OOO' AND length(inn) = 10)",
            name="inn_length",
        ),
    )


class CompanyMembership(IdentityMixin, UpdatedMixin, Base):
    __tablename__ = "company_memberships"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    __table_args__ = (UniqueConstraint("user_id", "company_id"),)


class CompanyFinancialMonth(IdentityMixin, UpdatedMixin, Base):
    __tablename__ = "company_financial_months"
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"))
    month: Mapped[date] = mapped_column()
    cash_inflow = mapped_column(MONEY, nullable=False)
    operating_outflow = mapped_column(MONEY, nullable=False)
    existing_debt_payment = mapped_column(MONEY, nullable=False)
    source: Mapped[FinancialSource] = mapped_column(enum_type(FinancialSource))
    __table_args__ = (
        UniqueConstraint("company_id", "month"),
        CheckConstraint(extract("day", month) == 1, name="month_first_day"),
        CheckConstraint(
            "cash_inflow >= 0 AND cash_inflow < 10000000000000000 AND "
            "operating_outflow >= 0 AND operating_outflow < 10000000000000000 AND "
            "existing_debt_payment >= 0 AND existing_debt_payment < 10000000000000000",
            name="nonnegative_finances",
        ),
        Index("ix_financial_month_company_month", "company_id", "month"),
    )
